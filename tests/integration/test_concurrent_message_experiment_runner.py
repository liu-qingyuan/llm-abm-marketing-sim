from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Literal, cast

import pytest

import llm_abm_sim.concurrent_message_experiment as concurrent_message_experiment_module
import llm_abm_sim.concurrent_message_report as concurrent_message_report_module
import llm_abm_sim.concurrent_robustness_report as concurrent_robustness_report_module
from llm_abm_sim import (
    ConcurrentMessageExperimentConfig,
    ConcurrentMessageExperimentRunner,
    ConcurrentRobustnessError,
    ConcurrentRobustnessErrorCode,
    ConcurrentRobustnessManifest,
    ConcurrentRobustnessStudy,
    ConcurrentRobustnessStudyResult,
    ConcurrentRobustnessStudyStatus,
    rebuild_concurrent_message_report,
)
from llm_abm_sim.concurrent_campaign_diagnostics import validate_concurrent_validation_summary
from llm_abm_sim.concurrent_execution_journal import (
    CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL,
    CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON,
    CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR,
    CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON,
    ConcurrentExecutionJournal,
    derive_concurrent_execution_workspace,
)
from llm_abm_sim.concurrent_message_experiment import authoritative_message_definitions
from llm_abm_sim.concurrent_message_renderer import _legacy_render_report, render_report
from llm_abm_sim.concurrent_message_report import close_concurrent_message_artifacts
from llm_abm_sim.decision import (
    CachedDecisionAdapter,
    DecisionInput,
    EngageDecision,
    InMemoryDecisionCache,
    LLMDecisionAdapter,
    ProviderDecisionError,
)
from llm_abm_sim.final_research import TARGET_VIDEO_ID
from llm_abm_sim.prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from llm_abm_sim.prompt_field_summary import (
    CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
    CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
)
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.provider_request_contract import STRUCTURED_OUTPUT_SCHEMA_HASH
from llm_abm_sim.providers.openai_compatible import (
    OpenAICompatibleDecisionAdapter,
    ProviderResponseEnvelope,
    _OpenAISDKClient,
)
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
        crash_after_calls: int | None = None,
    ) -> None:
        self.name = name
        self.prompt_version = prompt_version
        self.positive_user_ids = positive_user_ids
        self.fail_pairs = fail_pairs
        self.crash_after_calls = crash_after_calls
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
        if self.crash_after_calls is not None and self.request_invocations >= self.crash_after_calls:
            raise RuntimeError(f"{self.name} crash after {self.crash_after_calls} calls")
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


def _sdk_wrapper_stub(client: _SequencedEnvelopeClient) -> _OpenAISDKClient:
    sdk_client = object.__new__(_OpenAISDKClient)
    cast(Any, sdk_client).create_response = client.create_response
    return sdk_client


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_manifest_hashes(run_dir: Path, *artifact_keys: str) -> None:
    manifest_path = run_dir / "artifact_manifest.json"
    manifest = _read_json(manifest_path)
    for artifact_key in artifact_keys:
        relative_path = manifest["artifacts"][artifact_key]
        manifest["sha256"][artifact_key] = _sha256(run_dir / relative_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _assert_same_files(left_dir: Path, right_dir: Path, filenames: list[str]) -> None:
    for filename in filenames:
        assert (left_dir / filename).read_bytes() == (right_dir / filename).read_bytes(), filename


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
    usage_status: Literal["complete", "missing", "malformed"] = "complete",
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


def test_concurrent_message_artifact_closure_is_read_only_and_renderer_hash_dispatch(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )
    output_dir = ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="closure-primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs=set(),
        ),
        _ScriptedConcurrentAdapter(
            name="closure-shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs=set(),
        ),
    ).run_and_write(tmp_path / "closure-run")

    before = {path.name: path.read_bytes() for path in output_dir.iterdir() if path.is_file()}
    closure = close_concurrent_message_artifacts(output_dir)
    after = {path.name: path.read_bytes() for path in output_dir.iterdir() if path.is_file()}

    assert after == before
    expected_hash = hashlib.sha256(closure.report_html.encode("utf-8")).hexdigest()
    legacy_html = _legacy_render_report(closure.report_payload)
    legacy_hash = hashlib.sha256(legacy_html.encode("utf-8")).hexdigest()
    assert closure.report_html != legacy_html
    assert render_report(closure.report_payload) == closure.report_html
    assert render_report(closure.report_payload, expected_sha256=expected_hash) == closure.report_html
    assert render_report(closure.report_payload, expected_sha256=legacy_hash) == legacy_html
    with pytest.raises(ValueError, match="no concurrent message renderer matched"):
        render_report(closure.report_payload, expected_sha256="0" * 64)

    report_before_failure = (output_dir / "report.html").read_bytes()
    (output_dir / "concurrent_message_users.json").unlink()
    with pytest.raises(FileNotFoundError, match="requires"):
        close_concurrent_message_artifacts(output_dir)
    assert (output_dir / "report.html").read_bytes() == report_before_failure


def test_concurrent_message_report_rebuild_derives_immutable_destination(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )
    source_dir = ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs={(0, "message_3", "u4")},
        ),
        _ScriptedConcurrentAdapter(
            name="shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs={(0, "message_2", "u3")},
        ),
    ).run_and_write(tmp_path / "immutable-source")
    source_before = {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}
    source_manifest = _read_json(source_dir / "artifact_manifest.json")
    destination_dir = tmp_path / "presentation" / "candidate"

    report_path = rebuild_concurrent_message_report(source_dir, destination_dir=destination_dir)

    assert report_path == destination_dir / "report.html"
    assert destination_dir.is_dir()
    assert {path.name for path in destination_dir.iterdir() if path.is_file()} == set(source_before)
    assert source_before == {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}
    for relative_path in source_manifest["artifacts"].values():
        if relative_path != "report.html":
            assert (destination_dir / relative_path).read_bytes() == (source_dir / relative_path).read_bytes()
    destination_manifest = _read_json(destination_dir / "artifact_manifest.json")
    assert destination_manifest["sha256"]["report_html"] == _sha256(destination_dir / "report.html")
    close_concurrent_message_artifacts(destination_dir)
    assert rebuild_concurrent_message_report(destination_dir) == destination_dir / "report.html"


def test_concurrent_message_report_rebuild_destination_uses_editorial_default_for_legacy_source(
    tmp_path: Path,
) -> None:
    source_dir = _make_validation_report_source(tmp_path, "legacy-source")
    source_closure = close_concurrent_message_artifacts(source_dir)
    legacy_html = _legacy_render_report(source_closure.report_payload)
    (source_dir / "report.html").write_text(legacy_html, encoding="utf-8")
    source_manifest = _read_json(source_dir / "artifact_manifest.json")
    source_manifest["sha256"]["report_html"] = _sha256(source_dir / "report.html")
    (source_dir / "artifact_manifest.json").write_text(
        json.dumps(source_manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    destination_dir = tmp_path / "current-presentation"

    rebuild_concurrent_message_report(source_dir, destination_dir=destination_dir)

    assert (destination_dir / "report.html").read_text(encoding="utf-8") == render_report(source_closure.report_payload)
    assert (destination_dir / "report.html").read_text(encoding="utf-8") != legacy_html


def _make_validation_report_source(tmp_path: Path, name: str) -> Path:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )
    return ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs={(0, "message_3", "u4")},
        ),
        _ScriptedConcurrentAdapter(
            name="shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs={(0, "message_2", "u3")},
        ),
    ).run_and_write(tmp_path / name)


def test_concurrent_message_report_rebuild_rejects_invalid_source_before_staging(tmp_path: Path) -> None:
    source_dir = _make_validation_report_source(tmp_path, "invalid-source")
    (source_dir / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    destination_dir = tmp_path / "presentation-candidate"

    with pytest.raises(ValueError, match="unlisted artifacts"):
        rebuild_concurrent_message_report(source_dir, destination_dir=destination_dir)

    assert not destination_dir.exists()
    assert not list(tmp_path.glob(".presentation-candidate.*.staging"))


def test_concurrent_message_report_rebuild_cleans_staging_on_render_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = _make_validation_report_source(tmp_path, "render-failure-source")
    destination_dir = tmp_path / "presentation-candidate"

    def fail_render(payload: object, *, expected_sha256: str | None = None) -> str:
        del payload, expected_sha256
        raise RuntimeError("render failed")

    monkeypatch.setattr(concurrent_message_report_module, "render_report", fail_render)
    with pytest.raises(RuntimeError, match="render failed"):
        rebuild_concurrent_message_report(source_dir, destination_dir=destination_dir)

    assert not destination_dir.exists()
    assert not list(tmp_path.glob(".presentation-candidate.*.staging"))


def test_concurrent_message_report_rebuild_cleans_staging_on_copy_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = _make_validation_report_source(tmp_path, "copy-failure-source")
    destination_dir = tmp_path / "copy-failure-candidate"

    def fail_copy(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        del source, destination
        raise OSError("copy failed")

    monkeypatch.setattr(concurrent_message_report_module.shutil, "copyfile", fail_copy)
    with pytest.raises(OSError, match="copy failed"):
        rebuild_concurrent_message_report(source_dir, destination_dir=destination_dir)

    assert not destination_dir.exists()
    assert not list(tmp_path.glob(".copy-failure-candidate.*.staging"))


def test_concurrent_message_report_rebuild_rejects_source_file_set_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = _make_validation_report_source(tmp_path, "source-mutation-source")
    destination_dir = tmp_path / "source-mutation-candidate"
    original_render = concurrent_message_report_module.render_report
    unexpected_path = source_dir / "unexpected-during-rebuild.txt"

    def mutate_source(payload: object, *, expected_sha256: str | None = None) -> str:
        unexpected_path.write_text("unexpected", encoding="utf-8")
        return original_render(payload, expected_sha256=expected_sha256)

    monkeypatch.setattr(concurrent_message_report_module, "render_report", mutate_source)
    with pytest.raises(ValueError, match="artifact set changed"):
        rebuild_concurrent_message_report(source_dir, destination_dir=destination_dir)

    assert not destination_dir.exists()
    assert not list(tmp_path.glob(".source-mutation-candidate.*.staging"))
    unexpected_path.unlink()


def test_concurrent_message_report_rebuild_rejects_unsafe_destinations(tmp_path: Path) -> None:
    source_dir = _make_validation_report_source(tmp_path, "unsafe-source")
    existing_dir = tmp_path / "existing-candidate"
    existing_dir.mkdir()

    with pytest.raises(FileExistsError, match="already exists"):
        rebuild_concurrent_message_report(source_dir, destination_dir=existing_dir)
    with pytest.raises(ValueError, match="must not overlap"):
        rebuild_concurrent_message_report(source_dir, destination_dir=source_dir / "nested-candidate")
    with pytest.raises(ValueError, match="must not contain"):
        rebuild_concurrent_message_report(source_dir, destination_dir=tmp_path / ".." / "escaped-candidate")

    source_link = tmp_path / "source-link"
    os.symlink(source_dir, source_link, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        rebuild_concurrent_message_report(source_link, destination_dir=tmp_path / "linked-source-candidate")

    destination_link = tmp_path / "destination-link"
    os.symlink(source_dir, destination_link, target_is_directory=True)
    with pytest.raises(FileExistsError, match="already exists"):
        rebuild_concurrent_message_report(source_dir, destination_dir=destination_link)

    assert not list(tmp_path.glob(".linked-source-candidate.*.staging"))


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
    diagnostics = json.loads((output_dir / "concurrent_campaign_diagnostics.json").read_text(encoding="utf-8"))
    pair_rows = _read_csv(output_dir / "concurrent_runtime_pairs.csv")
    terminal_rows = _read_csv(output_dir / "concurrent_runtime_terminal_rows.csv")
    candidate_rows = _read_csv(output_dir / "concurrent_runtime_candidates.csv")
    step_rows = json.loads((output_dir / "concurrent_runtime_steps.json").read_text(encoding="utf-8"))
    report_html = (output_dir / "report.html").read_text(encoding="utf-8")
    report_payload = _read_json(output_dir / "concurrent_message_report_payload.json")
    users_document = _read_json(output_dir / "concurrent_message_users.json")
    decision_trace_document = _read_json(output_dir / "concurrent_message_decision_trace.json")
    runtime_document = _read_json(output_dir / "concurrent_message_runtime.json")
    diagnostics_document = _read_json(output_dir / "concurrent_message_diagnostics.json")
    field_lineage_document = _read_json(output_dir / "concurrent_message_field_lineage.json")
    sample_manifest = _read_json(output_dir / "sample_manifest.json")
    manifest = _read_json(output_dir / "artifact_manifest.json")

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
    assert diagnostics["schema_version"] == "concurrent-campaign-diagnostics-v1"
    assert diagnostics["campaign_funnel"]["actual_exposures"] == 60
    assert diagnostics["campaign_funnel"]["below_delivery_capacity_pairs"] == 30
    assert diagnostics["campaign_feedback_effect"]["overall"]["message_batch_count"] == 6
    assert diagnostics["campaign_feedback_effect"]["calls_decision_adapter"] is False
    assert diagnostics["demographic_decision_sensitivity"]["reason_screening"]["flagged_pair_count"] == 0
    validate_concurrent_validation_summary(validation, diagnostics)
    assert report_payload["schema_version"] == "concurrent-message-report-payload-v1"
    assert users_document["schema_version"] == "concurrent-message-users-v1"
    assert decision_trace_document["schema_version"] == "concurrent-message-decision-trace-v1"
    assert runtime_document["schema_version"] == "concurrent-message-runtime-v1"
    assert diagnostics_document["schema_version"] == "concurrent-message-diagnostics-v1"
    assert field_lineage_document["schema_version"] == "concurrent-message-field-lineage-v1"
    assert manifest["schema_version"] == "concurrent-message-artifact-manifest-v1"
    assert manifest["primary_prompt_token"] == CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    assert manifest["shadow_prompt_token"] == CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION
    assert report_payload["downloads"]["manifest"] == "artifact_manifest.json"
    assert report_payload["run"]["prompt_tokens"] == {
        "primary": CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        "shadow": CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
    }
    assert 'data-testid="editorial-report"' in report_html
    assert 'data-testid="run-formal-status"' in report_html
    assert "Campaign Funnel" in report_html
    assert 'data-testid="run-sample-users"' in report_html
    assert 'data-testid="run-llm-decision-section"' in report_html
    assert 'data-testid="run-feedback-changed-total"' in report_html
    assert 'data-testid="run-downloads-section"' in report_html
    assert "Approved downloads" in report_html
    assert 'data-testid="run-exposure-ranking-section"' in report_html
    assert all("nickname" not in row and "bio" not in row and "signature" not in row for row in sample_manifest)
    assert all("nickname" not in row and "bio" not in row and "signature" not in row for row in users_document["rows"])
    first_trace = decision_trace_document["rows"][0]
    assert first_trace["primary_prompt_version"] == CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    assert first_trace["shadow_prompt_version"] == CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION
    assert "nickname" not in first_trace["primary_context"]
    assert "bio" not in first_trace["primary_context"]
    original_html = report_html
    assert rebuild_concurrent_message_report(output_dir) == output_dir / "report.html"
    assert (output_dir / "report.html").read_text(encoding="utf-8") == original_html

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
    assert all(row["personalized_delivery_score_full_precision"] for row in first_batch_candidates)
    assert all(row["base_network_relevance_full_precision"] for row in first_batch_candidates)

    assert step_rows[0]["deduplicated_committed_primary_positive_user_ids"] == ["u1"]
    assert [message["message_id"] for message in step_rows[0]["messages"]] == ["message_1", "message_2", "message_3"]

    second_batch_message_summaries = {message["message_id"]: message for message in step_rows[1]["messages"]}
    assert (
        second_batch_message_summaries["message_1"]["selected_user_ids"]
        != second_batch_message_summaries["message_3"]["selected_user_ids"]
    )
    assert "u23" in second_batch_message_summaries["message_3"]["selected_user_ids"]
    assert "u12" in second_batch_message_summaries["message_1"]["selected_user_ids"]

    u11_second_batch_rows = [row for row in candidate_rows if row["time_step"] == "1" and row["user_id"] == "u11"]
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
    assert primary_failure_pair["shadow_gender"] == "female"

    shadow_failure_pair = next(row for row in pair_rows if row["message_id"] == "message_2" and row["user_id"] == "u3")
    assert shadow_failure_pair["primary_status"] == "succeeded"
    assert shadow_failure_pair["shadow_status"] == "provider_failed"

    validation_tampered = json.loads(json.dumps(validation))
    validation_tampered["counts"]["actual_exposures"] = 59
    with pytest.raises(ValueError, match="counts.actual_exposures"):
        validate_concurrent_validation_summary(validation_tampered, diagnostics)

    assert len(primary_adapter.calls) == 60
    assert len(shadow_adapter.calls) == 60
    primary_prompt = cast(str, primary_adapter.calls[0]["prompt_text"])
    shadow_prompt = cast(str, shadow_adapter.calls[0]["prompt_text"])
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
    primary_terminal = next(
        row for row in terminal_rows if row["pair_id"] == first_pair_id and row["decision_variant"] == "primary"
    )
    shadow_terminal = next(
        row for row in terminal_rows if row["pair_id"] == first_pair_id and row["decision_variant"] == "shadow"
    )
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


def test_concurrent_message_runner_persists_operational_journal_and_status(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )
    output_dir = ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs={(0, "message_3", "u4")},
        ),
        _ScriptedConcurrentAdapter(
            name="shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs={(0, "message_2", "u3")},
        ),
    ).run_and_write(tmp_path / "journaled-run")

    workspace_dir = derive_concurrent_execution_workspace(output_dir)
    assert workspace_dir.is_dir()
    assert (workspace_dir / CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON).is_file()
    assert (workspace_dir / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL).is_file()
    assert (workspace_dir / CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON).is_file()
    assert not (output_dir / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL).exists()
    assert not (output_dir / CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON).exists()

    status = _read_json(workspace_dir / CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON)
    assert status["schema_version"] == "concurrent-message-execution-status-v1"
    assert status["lifecycle"] == "published"
    assert status["final_source_path"] == str(output_dir)
    assert status["final_source_hash"]
    assert status["deploy_eligibility"] is False
    assert status["planned_batch_count"] == 2
    assert status["planned_pair_count"] == 60
    assert status["planned_variant_count"] == 120
    assert status["started_variant_count"] == 120
    assert status["terminal_variant_count"] == 120
    assert status["closed_pair_count"] == 60
    assert status["committed_batch_count"] == 2
    assert status["last_durable_identity"]["record_type"] == "event"
    assert status["last_durable_identity"]["event_type"] == "run_published"

    snapshot_dir = workspace_dir / CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR
    snapshot_paths = sorted(snapshot_dir.glob("*.json"))
    assert snapshot_paths
    snapshot = _read_json(snapshot_paths[0])
    snapshot["payload"]["planned_variant_count"] += 1
    snapshot_paths[0].write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="snapshot hash mismatch"):
        ConcurrentExecutionJournal.open_existing(workspace_dir).status()


def test_concurrent_message_report_rebuild_rejects_crossed_prompt_token(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )
    output_dir = ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs={(0, "message_3", "u4")},
        ),
        _ScriptedConcurrentAdapter(
            name="shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs={(0, "message_2", "u3")},
        ),
    ).run_and_write(tmp_path / "crossed-token-run")

    original_html = (output_dir / "report.html").read_text(encoding="utf-8")
    trace_path = output_dir / "concurrent_message_decision_trace.json"
    trace = _read_json(trace_path)
    trace["primary_prompt_token"] = CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION
    trace["rows"][0]["primary_prompt_version"] = CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    _rewrite_manifest_hashes(output_dir, "decision_trace_json")

    with pytest.raises(ValueError, match="crossed or unsupported Primary prompt token"):
        rebuild_concurrent_message_report(output_dir)
    assert (output_dir / "report.html").read_text(encoding="utf-8") == original_html


def test_concurrent_message_report_rebuild_rejects_extra_file_and_path_escape(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )
    output_dir = ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs={(0, "message_3", "u4")},
        ),
        _ScriptedConcurrentAdapter(
            name="shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs={(0, "message_2", "u3")},
        ),
    ).run_and_write(tmp_path / "extra-file-run")

    (output_dir / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError, match="unlisted artifacts"):
        rebuild_concurrent_message_report(output_dir)
    (output_dir / "unexpected.txt").unlink()

    manifest_path = output_dir / "artifact_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["artifacts"]["users_json"] = "../escape.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes the run directory"):
        rebuild_concurrent_message_report(output_dir)


def test_concurrent_message_report_rebuild_rejects_payload_and_duplicate_identity_tamper(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )
    output_dir = ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs={(0, "message_3", "u4")},
        ),
        _ScriptedConcurrentAdapter(
            name="shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs={(0, "message_2", "u3")},
        ),
    ).run_and_write(tmp_path / "tamper-run")

    original_html = (output_dir / "report.html").read_text(encoding="utf-8")
    payload_path = output_dir / "concurrent_message_report_payload.json"
    payload = _read_json(payload_path)
    payload["run"]["sample_size"] = 999
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    _rewrite_manifest_hashes(output_dir, "report_payload")
    with pytest.raises(ValueError, match="report payload does not close"):
        rebuild_concurrent_message_report(output_dir)
    assert (output_dir / "report.html").read_text(encoding="utf-8") == original_html

    output_dir = ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs={(0, "message_3", "u4")},
        ),
        _ScriptedConcurrentAdapter(
            name="shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs={(0, "message_2", "u3")},
        ),
    ).run_and_write(tmp_path / "duplicate-run")
    pair_rows = _read_csv(output_dir / "concurrent_runtime_pairs.csv")
    pair_rows.append(dict(pair_rows[0]))
    duplicate_csv_path = output_dir / "concurrent_runtime_pairs.csv"
    with duplicate_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pair_rows[0].keys()))
        writer.writeheader()
        writer.writerows(pair_rows)
    _rewrite_manifest_hashes(output_dir, "exposures_csv")
    with pytest.raises(ValueError, match="duplicate exposure identity"):
        rebuild_concurrent_message_report(output_dir)


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
        primary.decide(
            post, _concurrent_prompt_profile(user_id="u1", shadow=False), PeerContext(), PlatformContext(), 0
        )
        shadow.decide(post, _concurrent_prompt_profile(user_id="u1", shadow=True), PeerContext(), PlatformContext(), 0)

    assert len(primary_leaf.calls) == 1
    assert len(shadow_leaf.calls) == 1
    assert set(cast(InMemoryDecisionCache, primary.cache).decisions) != set(
        cast(InMemoryDecisionCache, shadow.cache).decisions
    )


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


def test_concurrent_message_runner_preserves_requested_and_observed_model_split(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path, user_count=3, seed_user_count=1)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=3,
        horizon=1,
        delivery_capacity=1,
        configuration_profile="validation",
    )
    requested_model = "gpt-5.4-mini"
    observed_model = "gpt-5.4-mini-2026-03-17"
    primary_client = _SequencedEnvelopeClient(
        [
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "primary", "confidence": 0.9, "action": "ignore"}',
                observed_model=observed_model,
            ),
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "primary", "confidence": 0.9, "action": "ignore"}',
                observed_model=observed_model,
            ),
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "primary", "confidence": 0.9, "action": "ignore"}',
                observed_model=observed_model,
            ),
        ]
    )
    shadow_client = _SequencedEnvelopeClient(
        [
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}',
                observed_model=observed_model,
            ),
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}',
                observed_model=observed_model,
            ),
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}',
                observed_model=observed_model,
            ),
        ]
    )
    primary_provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="mocked_openai_compatible",
            model=requested_model,
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
            model=requested_model,
            require_live_env=False,
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        ),
        client=shadow_client,
        sleep=lambda _delay: None,
    )

    run_dir = ConcurrentMessageExperimentRunner(config, primary_provider, shadow_provider).run_and_write(
        tmp_path / "requested-observed-model-split"
    )

    validation = _read_json(run_dir / "concurrent_validation.json")
    terminal_rows = _read_csv(run_dir / "concurrent_runtime_terminal_rows.csv")

    assert validation["variant_provider_accounting"]["primary"]["observed_model_counts"] == {observed_model: 3}
    assert validation["variant_provider_accounting"]["shadow"]["observed_model_counts"] == {observed_model: 3}
    assert validation["variant_provider_accounting"]["total"]["observed_model_counts"] == {observed_model: 6}
    assert all(json.loads(row["provider_metadata"])["model"] == requested_model for row in terminal_rows)
    assert all(json.loads(row["observed_model_counts"]) == {observed_model: 1} for row in terminal_rows)


def test_concurrent_message_runner_marks_sdk_wrapper_path_as_formal_but_deploy_blocked_on_validation_shape(
    tmp_path: Path,
) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path, user_count=3, seed_user_count=1)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=3,
        horizon=1,
        delivery_capacity=1,
        configuration_profile="validation",
    )
    requested_model = "gpt-5.4-mini"
    observed_model = "gpt-5.4-mini-2026-03-17"
    primary_client = _SequencedEnvelopeClient(
        [
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "primary formal", "confidence": 0.9, "action": "ignore"}',
                observed_model=observed_model,
                input_usage=9,
                output_usage=4,
            )
            for _ in range(3)
        ]
    )
    shadow_client = _SequencedEnvelopeClient(
        [
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "shadow formal", "confidence": 0.9, "action": "ignore"}',
                observed_model=observed_model,
                input_usage=8,
                output_usage=3,
            )
            for _ in range(3)
        ]
    )
    primary_provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="openai_compatible",
            model=requested_model,
            require_live_env=True,
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            max_retries=2,
        ),
        sleep=lambda _delay: None,
    )
    shadow_provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="openai_compatible",
            model=requested_model,
            require_live_env=True,
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            max_retries=2,
        ),
        sleep=lambda _delay: None,
    )
    primary_provider._build_live_client = lambda: _sdk_wrapper_stub(primary_client)  # type: ignore[method-assign]
    shadow_provider._build_live_client = lambda: _sdk_wrapper_stub(shadow_client)  # type: ignore[method-assign]

    output_dir = ConcurrentMessageExperimentRunner(config, primary_provider, shadow_provider).run_and_write(
        tmp_path / "concurrent-formal-validation-shape"
    )

    validation = json.loads((output_dir / "concurrent_validation.json").read_text(encoding="utf-8"))
    config_snapshot = json.loads((output_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    payload = json.loads((output_dir / "concurrent_message_report_payload.json").read_text(encoding="utf-8"))
    report_html = (output_dir / "report.html").read_text(encoding="utf-8")

    assert validation["sampling_status"] == "persisted_seed_first_formal_run"
    assert validation["production_deploy_eligible"] is False
    assert config_snapshot["sampling_status"] == "persisted_seed_first_formal_run"
    assert config_snapshot["production_deploy_eligible"] is False
    assert payload["run"]["sampling_status"] == "persisted_seed_first_formal_run"
    assert payload["run"]["production_deploy_eligible"] is False
    assert validation["variant_provider_accounting"]["primary"]["invocations"] == 3
    assert validation["variant_provider_accounting"]["shadow"]["invocations"] == 3
    assert validation["variant_provider_accounting"]["total"]["invocations"] == 6
    assert len(primary_client.calls) == 3
    assert len(shadow_client.calls) == 3
    assert "Formal" in report_html
    assert 'data-testid="run-formal-status"' in report_html


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
            _provider_response(
                '{"engage": false, "probability": 0.2, "reason": "retry success", "confidence": 0.9, "action": "ignore"}',
                input_usage=10,
                output_usage=5,
            ),
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "steady", "confidence": 0.9, "action": "ignore"}',
                input_usage=9,
                output_usage=4,
            ),
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "steady", "confidence": 0.9, "action": "ignore"}',
                input_usage=8,
                output_usage=4,
            ),
        ]
    )
    shadow_client = _SequencedEnvelopeClient(
        [
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}',
                input_usage=7,
                output_usage=3,
            ),
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}',
                input_usage=7,
                output_usage=3,
            ),
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}',
                input_usage=7,
                output_usage=3,
            ),
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
        row for row in terminal_rows if row["decision_variant"] == "primary" and row["message_id"] == "message_1"
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


def test_private_primary_only_consumer_runs_without_shadow_and_commits_only_positive_feedback(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )
    primary_adapter = _ScriptedConcurrentAdapter(
        name="primary-only",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={"u1"},
        fail_pairs={(0, "message_3", "u4")},
    )

    result = concurrent_message_experiment_module._PrimaryOnlyConcurrentRuntimeConsumer(
        config,
        primary_adapter,
    ).run_new(tmp_path / "primary-only-run")

    assert len(primary_adapter.calls) == 60
    assert len(result.primary_rows) == 60
    assert len(result.terminal_rows) == 60
    assert {row["decision_variant"] for row in result.terminal_rows} == {"primary"}
    assert len({(row["message_id"], row["user_id"]) for row in result.primary_rows}) == 60
    assert sum(row["primary_status"] == "provider_failed" for row in result.primary_rows) == 1
    batch_zero_selected = [message["selected_user_ids"] for message in result.step_rows[0]["messages"]]
    assert batch_zero_selected[0] == batch_zero_selected[1] == batch_zero_selected[2]
    assert result.step_rows[0]["deduplicated_committed_primary_positive_user_ids"] == ["u1"]
    assert "u4" not in result.step_rows[0]["deduplicated_committed_primary_positive_user_ids"]
    assert all("shadow" not in row for row in result.primary_rows)
    assert all(
        "shadow_provider_failed_user_ids" not in message for step in result.step_rows for message in step["messages"]
    )
    status = ConcurrentExecutionJournal.open_existing(result.workspace_root).status()
    assert status["lifecycle"] == "ready_to_finalize"
    assert status["planned_variant_count"] == 60
    assert status["terminal_variant_count"] == 60
    assert status["closed_pair_count"] == 60
    assert status["committed_batch_count"] == 2


def test_private_primary_only_consumer_resumes_durable_batch_without_replaying_terminals(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )
    baseline = concurrent_message_experiment_module._PrimaryOnlyConcurrentRuntimeConsumer(
        config,
        _ScriptedConcurrentAdapter(
            name="primary-only-resume",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs={(0, "message_3", "u4")},
        ),
    ).run_new(tmp_path / "primary-only-baseline")

    output_target = tmp_path / "primary-only-crash"
    with pytest.raises(RuntimeError, match="crash after 32 calls"):
        concurrent_message_experiment_module._PrimaryOnlyConcurrentRuntimeConsumer(
            config,
            _ScriptedConcurrentAdapter(
                name="primary-only-resume",
                prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
                positive_user_ids={"u1"},
                fail_pairs={(0, "message_3", "u4")},
                crash_after_calls=32,
            ),
        ).run_new(output_target)

    resumed_adapter = _ScriptedConcurrentAdapter(
        name="primary-only-resume",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={"u1"},
        fail_pairs={(0, "message_3", "u4")},
    )
    resumed = concurrent_message_experiment_module._PrimaryOnlyConcurrentRuntimeConsumer(
        config,
        resumed_adapter,
    ).resume(output_target)

    assert resumed.candidate_rows == baseline.candidate_rows
    assert resumed.primary_rows == baseline.primary_rows
    assert resumed.terminal_rows == baseline.terminal_rows
    assert resumed.step_rows == baseline.step_rows
    assert resumed_adapter.calls
    assert {call["time_step"] for call in resumed_adapter.calls} == {1}


@pytest.mark.parametrize("corruption", ["snapshot", "terminal", "identity"])
def test_private_primary_only_resume_rejects_corrupt_durable_state(
    tmp_path: Path,
    corruption: str,
) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )
    output_target = tmp_path / f"primary-only-corrupt-{corruption}"
    with pytest.raises(RuntimeError, match="crash after 32 calls"):
        concurrent_message_experiment_module._PrimaryOnlyConcurrentRuntimeConsumer(
            config,
            _ScriptedConcurrentAdapter(
                name="primary-only-corrupt",
                prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
                positive_user_ids={"u1"},
                fail_pairs=set(),
                crash_after_calls=32,
            ),
        ).run_new(output_target)

    workspace = derive_concurrent_execution_workspace(output_target)
    if corruption == "snapshot":
        snapshot_path = sorted((workspace / CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR).glob("*.json"))[-1]
        snapshot_path.write_text(snapshot_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    elif corruption == "terminal":
        journal_path = workspace / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL
        records = journal_path.read_text(encoding="utf-8").splitlines()
        terminal_index = max(
            index for index, raw in enumerate(records) if json.loads(raw).get("event_type") == "variant_terminal"
        )
        terminal_record = json.loads(records[terminal_index])
        terminal_record["payload"]["terminal_row"]["action"] = "share"
        records[terminal_index] = json.dumps(terminal_record, ensure_ascii=False, sort_keys=True)
        journal_path.write_text("\n".join(records) + "\n", encoding="utf-8")
    else:
        config = config.model_copy(update={"horizon": 3})

    resume_adapter = _ScriptedConcurrentAdapter(
        name="primary-only-corrupt",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={"u1"},
        fail_pairs=set(),
    )
    with pytest.raises(
        (ValueError, FileNotFoundError), match="snapshot hash mismatch|checksum mismatch|identity mismatch"
    ):
        concurrent_message_experiment_module._PrimaryOnlyConcurrentRuntimeConsumer(
            config,
            resume_adapter,
        ).resume(output_target)
    assert resume_adapter.calls == []


def test_concurrent_message_runner_resumes_crashed_batch_and_matches_baseline(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )

    baseline_output = ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs=set(),
        ),
        _ScriptedConcurrentAdapter(
            name="shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs=set(),
        ),
    ).run_and_write(tmp_path / "baseline-run")

    crash_output = tmp_path / "crash-resume-run"
    crashing_primary = _ScriptedConcurrentAdapter(
        name="primary",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={"u1"},
        fail_pairs=set(),
        crash_after_calls=5,
    )
    crashing_shadow = _ScriptedConcurrentAdapter(
        name="shadow",
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        positive_user_ids={"u2"},
        fail_pairs=set(),
    )
    with pytest.raises(RuntimeError, match="crash after 5 calls"):
        ConcurrentMessageExperimentRunner(config, crashing_primary, crashing_shadow).run_and_write(crash_output)

    workspace_dir = derive_concurrent_execution_workspace(crash_output)
    replay = ConcurrentExecutionJournal.open_existing(workspace_dir).replay()
    assert replay["status"]["lifecycle"] != "published"
    assert replay["status"]["closed_pair_count"] > 0

    resumed_primary = _ScriptedConcurrentAdapter(
        name="primary",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={"u1"},
        fail_pairs=set(),
    )
    resumed_shadow = _ScriptedConcurrentAdapter(
        name="shadow",
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        positive_user_ids={"u2"},
        fail_pairs=set(),
    )
    resumed_output = ConcurrentMessageExperimentRunner(config, resumed_primary, resumed_shadow).run_and_write(
        crash_output, mode="resume"
    )

    assert resumed_output == crash_output
    _assert_same_files(
        baseline_output,
        resumed_output,
        [
            "concurrent_runtime_candidates.csv",
            "concurrent_runtime_pairs.csv",
            "concurrent_runtime_terminal_rows.csv",
            "concurrent_runtime_steps.json",
            "concurrent_message_decision_trace.json",
            "concurrent_validation.json",
            "concurrent_campaign_diagnostics.json",
            "artifact_manifest.json",
            "report.html",
        ],
    )

    resumed_primary_calls = {(call["time_step"], call["message_id"], call["user_id"]) for call in resumed_primary.calls}
    resumed_shadow_calls = {(call["time_step"], call["message_id"], call["user_id"]) for call in resumed_shadow.calls}
    for record in replay["records"]:
        if record["record_type"] != "event" or record["event_type"] != "variant_terminal":
            continue
        call_key = (
            record["event_identity"]["time_step"],
            record["payload"]["message_id"],
            record["payload"]["user_id"],
        )
        if record["event_identity"]["decision_variant"] == "primary":
            assert call_key not in resumed_primary_calls
        else:
            assert call_key not in resumed_shadow_calls


def test_concurrent_message_runner_resume_after_finalization_is_idempotent(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )

    output_dir = ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="finalized-primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs=set(),
        ),
        _ScriptedConcurrentAdapter(
            name="finalized-shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs=set(),
        ),
    ).run_and_write(tmp_path / "finalized-run")

    workspace_dir = derive_concurrent_execution_workspace(output_dir)
    record_count = ConcurrentExecutionJournal.open_existing(workspace_dir).status()["record_count"]

    resume_primary = _ScriptedConcurrentAdapter(
        name="resume-primary",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={"u1"},
        fail_pairs=set(),
    )
    resume_shadow = _ScriptedConcurrentAdapter(
        name="resume-shadow",
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        positive_user_ids={"u2"},
        fail_pairs=set(),
    )
    resumed_output = ConcurrentMessageExperimentRunner(config, resume_primary, resume_shadow).run_and_write(
        output_dir, mode="resume"
    )

    assert resumed_output == output_dir
    assert resume_primary.calls == []
    assert resume_shadow.calls == []
    assert ConcurrentExecutionJournal.open_existing(workspace_dir).status()["record_count"] == record_count


def test_concurrent_message_runner_recovers_when_publish_marker_crashes_after_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )

    baseline_output = ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="crash-primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs=set(),
        ),
        _ScriptedConcurrentAdapter(
            name="crash-shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs=set(),
        ),
    ).run_and_write(tmp_path / "publish-marker-baseline")

    output_dir = tmp_path / "publish-marker-crash-run"
    crashing_primary = _ScriptedConcurrentAdapter(
        name="crash-primary",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={"u1"},
        fail_pairs=set(),
    )
    crashing_shadow = _ScriptedConcurrentAdapter(
        name="crash-shadow",
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        positive_user_ids={"u2"},
        fail_pairs=set(),
    )
    original_append = ConcurrentExecutionJournal.append
    crash_state = {"triggered": False}

    def _crashing_append(
        self: ConcurrentExecutionJournal,
        *,
        event_type: str,
        event_identity: dict[str, object],
        payload: dict[str, object],
        batch_snapshot_hash: str | None = None,
    ) -> dict[str, object]:
        if event_type == "run_published" and not crash_state["triggered"]:
            crash_state["triggered"] = True
            raise RuntimeError("crash after atomic rename before run_published")
        return original_append(
            self,
            event_type=event_type,
            event_identity=event_identity,
            payload=payload,
            batch_snapshot_hash=batch_snapshot_hash,
        )

    monkeypatch.setattr(ConcurrentExecutionJournal, "append", _crashing_append)
    with pytest.raises(RuntimeError, match="crash after atomic rename before run_published"):
        ConcurrentMessageExperimentRunner(config, crashing_primary, crashing_shadow).run_and_write(output_dir)

    workspace_dir = derive_concurrent_execution_workspace(output_dir)
    crashed_status = ConcurrentExecutionJournal.open_existing(workspace_dir).status()
    assert crashed_status["lifecycle"] == "durable_partial"
    assert crashed_status["finalization_started"] is True
    assert (output_dir / "artifact_manifest.json").is_file()

    resumed_primary = _ScriptedConcurrentAdapter(
        name="resume-primary",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={"u1"},
        fail_pairs=set(),
    )
    resumed_shadow = _ScriptedConcurrentAdapter(
        name="resume-shadow",
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        positive_user_ids={"u2"},
        fail_pairs=set(),
    )
    resumed_output = ConcurrentMessageExperimentRunner(config, resumed_primary, resumed_shadow).run_and_write(
        output_dir, mode="resume"
    )

    assert resumed_output == output_dir
    assert resumed_primary.calls == []
    assert resumed_shadow.calls == []
    _assert_same_files(
        baseline_output,
        resumed_output,
        [
            "concurrent_runtime_candidates.csv",
            "concurrent_runtime_pairs.csv",
            "concurrent_runtime_terminal_rows.csv",
            "concurrent_runtime_steps.json",
            "concurrent_message_decision_trace.json",
            "concurrent_validation.json",
            "concurrent_campaign_diagnostics.json",
            "artifact_manifest.json",
            "report.html",
        ],
    )
    assert ConcurrentExecutionJournal.open_existing(workspace_dir).status()["lifecycle"] == "published"


@pytest.mark.parametrize("crash_point", ["before_shadow_terminal", "before_pair_closed"])
def test_concurrent_message_runner_resumes_partial_pair_without_duplicate_terminals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_point: str,
) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )

    baseline_output = ConcurrentMessageExperimentRunner(
        config,
        _ScriptedConcurrentAdapter(
            name="primary",
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            positive_user_ids={"u1"},
            fail_pairs=set(),
        ),
        _ScriptedConcurrentAdapter(
            name="shadow",
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            positive_user_ids={"u2"},
            fail_pairs=set(),
        ),
    ).run_and_write(tmp_path / "partial-pair-baseline")

    output_dir = tmp_path / "partial-pair-crash-run"
    original_append = ConcurrentExecutionJournal.append
    crash_state = {"triggered": False}

    def _crashing_append(
        self: ConcurrentExecutionJournal,
        *,
        event_type: str,
        event_identity: dict[str, object],
        payload: dict[str, object],
        batch_snapshot_hash: str | None = None,
    ) -> dict[str, object]:
        before_shadow_terminal = (
            crash_point == "before_shadow_terminal"
            and event_type == "variant_terminal"
            and event_identity.get("decision_variant") == "shadow"
        )
        before_pair_closed = crash_point == "before_pair_closed" and event_type == "pair_closed"
        if (before_shadow_terminal or before_pair_closed) and not crash_state["triggered"]:
            crash_state["triggered"] = True
            raise RuntimeError(f"crash at {crash_point}")
        return original_append(
            self,
            event_type=event_type,
            event_identity=event_identity,
            payload=payload,
            batch_snapshot_hash=batch_snapshot_hash,
        )

    monkeypatch.setattr(ConcurrentExecutionJournal, "append", _crashing_append)
    crashing_primary = _ScriptedConcurrentAdapter(
        name="primary",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={"u1"},
        fail_pairs=set(),
    )
    crashing_shadow = _ScriptedConcurrentAdapter(
        name="shadow",
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        positive_user_ids={"u2"},
        fail_pairs=set(),
    )
    with pytest.raises(RuntimeError, match=f"crash at {crash_point}"):
        ConcurrentMessageExperimentRunner(config, crashing_primary, crashing_shadow).run_and_write(output_dir)

    workspace_dir = derive_concurrent_execution_workspace(output_dir)
    replay = ConcurrentExecutionJournal.open_existing(workspace_dir).replay()
    terminal_events = [
        record
        for record in replay["records"]
        if record["record_type"] == "event" and record["event_type"] == "variant_terminal"
    ]
    terminal_keys = [
        (record["event_identity"]["pair_id"], record["event_identity"]["decision_variant"])
        for record in terminal_events
    ]
    assert len(terminal_keys) == len(set(terminal_keys))

    resumed_primary = _ScriptedConcurrentAdapter(
        name="primary",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={"u1"},
        fail_pairs=set(),
    )
    resumed_shadow = _ScriptedConcurrentAdapter(
        name="shadow",
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        positive_user_ids={"u2"},
        fail_pairs=set(),
    )
    resumed_output = ConcurrentMessageExperimentRunner(config, resumed_primary, resumed_shadow).run_and_write(
        output_dir, mode="resume"
    )

    assert resumed_output == output_dir
    _assert_same_files(
        baseline_output,
        resumed_output,
        [
            "concurrent_runtime_candidates.csv",
            "concurrent_runtime_pairs.csv",
            "concurrent_runtime_terminal_rows.csv",
            "concurrent_runtime_steps.json",
            "concurrent_message_decision_trace.json",
            "concurrent_validation.json",
            "concurrent_campaign_diagnostics.json",
            "artifact_manifest.json",
            "report.html",
        ],
    )
    resumed_primary_calls = {(call["time_step"], call["message_id"], call["user_id"]) for call in resumed_primary.calls}
    resumed_shadow_calls = {(call["time_step"], call["message_id"], call["user_id"]) for call in resumed_shadow.calls}
    for record in terminal_events:
        call_key = (
            record["event_identity"]["time_step"],
            record["payload"]["message_id"],
            record["payload"]["user_id"],
        )
        if record["event_identity"]["decision_variant"] == "primary":
            assert call_key not in resumed_primary_calls
        else:
            assert call_key not in resumed_shadow_calls

    resumed_replay = ConcurrentExecutionJournal.open_existing(workspace_dir).replay()
    resumed_terminal_keys = [
        (record["event_identity"]["pair_id"], record["event_identity"]["decision_variant"])
        for record in resumed_replay["records"]
        if record["record_type"] == "event" and record["event_type"] == "variant_terminal"
    ]
    assert len(resumed_terminal_keys) == len(set(resumed_terminal_keys))


_ROBUSTNESS_MODELS = (
    "gpt-5.4-mini",
    "gpt-5.4-2026-03-05",
    "gpt-5.5-2026-04-23",
    "gpt-5.6-sol",
)
_ROBUSTNESS_COMPONENTS = (
    "base_network_relevance",
    "campaign_engaged_neighbor_signal",
    "normalized_message_user_fit",
)


def _robustness_weight_points() -> list[dict[str, object]]:
    baseline = {
        "base_network_relevance": 0.50,
        "campaign_engaged_neighbor_signal": 0.30,
        "normalized_message_user_fit": 0.20,
    }
    points: list[dict[str, object]] = [
        {
            "scenario_id": "baseline",
            "weights": baseline,
            "transfer_from": None,
            "transfer_to": None,
            "transfer_mass": 0.0,
        }
    ]
    for left, right in (
        (_ROBUSTNESS_COMPONENTS[0], _ROBUSTNESS_COMPONENTS[1]),
        (_ROBUSTNESS_COMPONENTS[0], _ROBUSTNESS_COMPONENTS[2]),
        (_ROBUSTNESS_COMPONENTS[1], _ROBUSTNESS_COMPONENTS[2]),
    ):
        for transfer_mass in (0.05, 0.10, 0.15):
            for source, target in ((left, right), (right, left)):
                weights = dict(baseline)
                weights[source] -= transfer_mass
                weights[target] += transfer_mass
                points.append(
                    {
                        "scenario_id": f"transfer-{source}-to-{target}-{transfer_mass:.2f}",
                        "weights": weights,
                        "transfer_from": source,
                        "transfer_to": target,
                        "transfer_mass": transfer_mass,
                    }
                )
    return points


def _robustness_manifest_for_source(
    source_dir: Path,
    *,
    output_identity: str,
) -> ConcurrentRobustnessManifest:
    closure = close_concurrent_message_artifacts(source_dir)
    config = closure.source_evidence.config_snapshot
    sample_rows = closure.source_evidence.sample_manifest_rows
    prompt_cells = []
    required_observed_models = {
        "gpt-5.4-mini": "gpt-5.4-mini-2026-03-17",
        "gpt-5.4-2026-03-05": "gpt-5.4-2026-03-05",
        "gpt-5.5-2026-04-23": "gpt-5.5-2026-04-23",
        "gpt-5.6-sol": "gpt-5.6-sol",
    }
    for prompt in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all():
        for requested_model in _ROBUSTNESS_MODELS:
            prompt_cells.append(
                {
                    "cell_id": f"{prompt.variant_id}::{requested_model}",
                    "prompt_variant": prompt.variant_id,
                    "prompt_version": prompt.prompt_version,
                    "prompt_canonical_hash": prompt.canonical_hash,
                    "requested_model": requested_model,
                    "required_observed_model": required_observed_models[requested_model],
                }
            )
    source_kind = "formal" if config["configuration_profile"] == "production" else "fixture"
    logical_per_cell = int(config["horizon"]) * int(config["delivery_capacity"]) * 3
    source_hashes = closure.artifact_hashes
    sample_identity = hashlib.sha256(
        json.dumps(
            [str(row["user_id"]) for row in sample_rows],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ConcurrentRobustnessManifest.model_validate(
        {
            "schema_version": "concurrent-robustness-manifest-v1",
            "source": {
                "kind": source_kind,
                "source_id": source_dir.name,
                "source_dir": str(source_dir.resolve()),
                "manifest_schema": closure.manifest.schema_version,
                "manifest_sha256": source_hashes["artifact_manifest.json"],
                "artifacts": [
                    {"relative_path": relative_path, "sha256": digest}
                    for relative_path, digest in sorted(source_hashes.items())
                ],
                "candidate_artifact": "concurrent_runtime_candidates.csv",
                "feedback_artifact": "concurrent_runtime_steps.json",
            },
            "sample": {
                "sample_size": len(sample_rows),
                "sample_identity": sample_identity,
                "sample_manifest_sha256": source_hashes["sample_manifest.json"],
                "sample_audit_sha256": source_hashes["seed_first_sample_audit.json"],
            },
            "message_ids": [str(row["message_id"]) for row in closure.source_evidence.message_snapshot],
            "message_snapshot_sha256": source_hashes["message_snapshot.json"],
            "ranking_contract": {
                "schema_version": "concurrent-robustness-ranking-contract-v1",
                "p95_normalization_token": "holdout-safe-log1p-p95-weighted-degree-v1",
                "component_contract_token": "concurrent-ranking-components-v1",
                "components": list(_ROBUSTNESS_COMPONENTS),
                "tie_break_token": "score-desc-user-id-asc-v1",
                "schedule_token": "shared-seed-launch-then-per-message-top-k-v1",
                "score_precision_token": "binary64-full-precision-no-rounding-v1",
                "ranking_formula": config["ranking_formula"],
                "feedback_formula": config["engaged_neighbor_formula"],
                "horizon": int(config["horizon"]),
                "delivery_capacity": int(config["delivery_capacity"]),
            },
            "weight_points": _robustness_weight_points(),
            "prompt_model_cells": prompt_cells,
            "request_contract": {
                "schema_version": "provider-request-contract-v1",
                "provider": "openai_compatible",
                "wire_api": "responses",
                "reasoning_effort": "low",
                "output_token_ceiling": 256,
                "timeout_seconds": 30.0,
                "max_retries": 2,
                "retry_backoff_seconds": 0.5,
                "structured_output_schema_version": "engage-decision-output-v1",
                "structured_output_schema_hash": STRUCTURED_OUTPUT_SCHEMA_HASH,
                "omitted_parameters": ["temperature", "top_p", "seed"],
                "decision_store_policy": "fresh-per-cell-no-cache-v1",
            },
            "request_caps": {
                "weight_logical_judgment_cap": 0,
                "logical_judgments_per_cell": logical_per_cell,
                "logical_judgment_cap": logical_per_cell * 16,
                "physical_attempt_cap": logical_per_cell * 16 * 3,
                "fee_ceiling_usd": 0.0,
            },
            "practical_thresholds": {
                "engagement_rate_absolute": 0.05,
                "decision_probability_absolute": 0.05,
                "audience_jaccard_distance": 0.10,
                "terminal_unique_positive_user_fraction": 0.05,
                "terminal_unique_positive_user_count": math.ceil(len(sample_rows) * 0.05),
            },
            "authorization_reference": "static-only:no-live-authorization",
            "output_identity": output_identity,
        }
    )


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _robustness_cell_source_identity(
    *,
    manifest_sha256: str,
    source_identity: dict[str, object],
    cell_id: str,
) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(
            {
                "manifest_sha256": manifest_sha256,
                "source_identity": source_identity,
                "cell_id": cell_id,
            }
        )
    ).hexdigest()


def _install_deterministic_robustness_cell_fixture(
    workspace: Path,
    manifest: ConcurrentRobustnessManifest,
) -> dict[str, object]:
    manifest_sha256 = _sha256(workspace / "study_manifest.json")
    manifest_payload = manifest.model_dump(mode="json")
    ranking_contract = cast(dict[str, object], manifest_payload["ranking_contract"])
    request_contract = cast(dict[str, object], manifest_payload["request_contract"])
    ranking_contract_sha256 = hashlib.sha256(_canonical_json_bytes(ranking_contract)).hexdigest()
    request_contract_sha256 = hashlib.sha256(_canonical_json_bytes(request_contract)).hexdigest()
    source_identity: dict[str, object] = {
        "source_id": manifest.source.source_id,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "sample_identity": manifest.sample.sample_identity,
        "message_snapshot_sha256": manifest.message_snapshot_sha256,
        "ranking_contract_sha256": ranking_contract_sha256,
    }
    positive_actions = ("like", "comment", "share")
    cells: list[dict[str, object]] = []
    total_physical_attempts = 0
    logical_per_cell = manifest.request_caps.logical_judgments_per_cell
    for cell_index, manifest_cell in enumerate(manifest.prompt_model_cells):
        prompt_index = cell_index // len(_ROBUSTNESS_MODELS)
        model_index = cell_index % len(_ROBUSTNESS_MODELS)
        observed_model = manifest_cell.required_observed_model
        assert observed_model is not None
        cell_source_identity = _robustness_cell_source_identity(
            manifest_sha256=manifest_sha256,
            source_identity=source_identity,
            cell_id=manifest_cell.cell_id,
        )
        terminal_rows: list[dict[str, object]] = []
        step_rows: list[dict[str, object]] = []
        pair_schedule_position = 0
        campaign_positive_users: set[str] = set()
        cell_physical_attempts = 0
        for time_step in range(manifest.ranking_contract.horizon):
            frozen_positive_users = sorted(campaign_positive_users, key=lambda value: int(value[1:]))
            batch_positive_users: set[str] = set()
            message_steps: list[dict[str, object]] = []
            for message_index, message_id in enumerate(manifest.message_ids):
                if time_step == 0:
                    selected_users = [f"u{number}" for number in range(1, manifest.ranking_contract.delivery_capacity + 1)]
                else:
                    selected_users = [f"u{number}" for number in range(11, 20)]
                    replacement = 20 if cell_index == 0 else 21 + ((cell_index + message_index) % 10)
                    selected_users.append(f"u{replacement}")
                message_positive_users: list[str] = []
                message_failed_users: list[str] = []
                for user_id in selected_users:
                    user_number = int(user_id[1:])
                    provider_failed = (
                        cell_index == 1
                        and time_step == manifest.ranking_contract.horizon - 1
                        and message_index == 2
                        and user_id == selected_users[-1]
                    )
                    engage = (user_number + prompt_index + model_index + message_index) % 3 != 0
                    action = positive_actions[(user_number + cell_index + message_index) % len(positive_actions)] if engage else "ignore"
                    request_invocations = manifest.request_contract.max_retries + 1 if provider_failed else 1
                    provider_response_count = 0 if provider_failed else 1
                    successful_decision_count = 0 if provider_failed else 1
                    probability = None if provider_failed else round((0.72 if engage else 0.22) + prompt_index * 0.03 + model_index * 0.02, 6)
                    confidence = None if provider_failed else round(0.82 - prompt_index * 0.02 + model_index * 0.01, 6)
                    pair_id = f"{user_id}:{message_id}:{time_step}"
                    terminal_rows.append(
                        {
                            "terminal_row_id": f"{pair_id}:primary",
                            "pair_id": pair_id,
                            "pair_schedule_position": pair_schedule_position,
                            "time_step": time_step,
                            "message_id": message_id,
                            "user_id": user_id,
                            "is_seed": time_step == 0,
                            "selection_reason": "shared_seed" if time_step == 0 else "personalized_top_k",
                            "decision_variant": "primary",
                            "prompt_version": manifest_cell.prompt_version,
                            "prompt_canonical_hash": manifest_cell.prompt_canonical_hash,
                            "requested_model": manifest_cell.requested_model,
                            "request_contract_sha256": request_contract_sha256,
                            "terminal_status": "provider_failed" if provider_failed else "succeeded",
                            "engage": None if provider_failed else engage,
                            "probability": probability,
                            "confidence": confidence,
                            "action": None if provider_failed else action,
                            "reason": None if provider_failed else "deterministic fixture decision",
                            "failure_type": "fixture_provider_failure" if provider_failed else None,
                            "request_invocations": request_invocations,
                            "provider_response_count": provider_response_count,
                            "successful_decision_count": successful_decision_count,
                            "observed_model_counts": {} if provider_failed else {observed_model: 1},
                            "observed_model_missing_response_count": 0,
                            "observed_model_malformed_response_count": 0,
                        }
                    )
                    pair_schedule_position += 1
                    cell_physical_attempts += request_invocations
                    if provider_failed:
                        message_failed_users.append(user_id)
                    elif action in positive_actions:
                        message_positive_users.append(user_id)
                        batch_positive_users.add(user_id)
                message_steps.append(
                    {
                        "message_id": message_id,
                        "selected_user_ids": selected_users,
                        "seed_user_ids": selected_users if time_step == 0 else [],
                        "primary_positive_user_ids": message_positive_users,
                        "primary_provider_failed_user_ids": message_failed_users,
                    }
                )
            campaign_positive_users.update(batch_positive_users)
            step_rows.append(
                {
                    "time_step": time_step,
                    "frozen_campaign_engaged_user_ids": frozen_positive_users,
                    "deduplicated_committed_primary_positive_user_ids": sorted(
                        batch_positive_users,
                        key=lambda value: int(value[1:]),
                    ),
                    "messages": message_steps,
                }
            )
        assert len(terminal_rows) == logical_per_cell
        total_physical_attempts += cell_physical_attempts
        cells.append(
            {
                "cell_index": cell_index,
                "cell_id": manifest_cell.cell_id,
                "prompt_variant": manifest_cell.prompt_variant,
                "prompt_version": manifest_cell.prompt_version,
                "prompt_canonical_hash": manifest_cell.prompt_canonical_hash,
                "requested_model": manifest_cell.requested_model,
                "observed_model": observed_model,
                "source_identity_sha256": cell_source_identity,
                "request_contract_sha256": request_contract_sha256,
                "logical_judgment_count": len(terminal_rows),
                "physical_attempt_count": cell_physical_attempts,
                "terminal_rows": terminal_rows,
                "step_rows": step_rows,
            }
        )

    evidence: dict[str, object] = {
        "schema_version": "concurrent-robustness-cell-evidence-v1",
        "evidence_profile": "deterministic_fixture",
        "manifest_sha256": manifest_sha256,
        "source_identity": source_identity,
        "request_contract": request_contract,
        "request_contract_sha256": request_contract_sha256,
        "message_ids": list(manifest.message_ids),
        "cell_count": len(cells),
        "logical_judgment_count": logical_per_cell * len(cells),
        "physical_attempt_count": total_physical_attempts,
        "external_request_invocations": 0,
        "live_api_triggered": False,
        "production_deploy_eligible": False,
        "conditional_scope": "fixed-sample-fixed-graph-one-realized-path-per-cell",
        "claim_statements": [
            "Results are descriptive and conditional on the fixed sample, fixed graph, and one realized path per cell.",
            "Below-threshold values are labelled small observed differences only.",
            "One path per cell leaves model stochasticity unestimated.",
        ],
        "cells": cells,
    }
    evidence_path = workspace / "prompt_model_cell_evidence.json"
    evidence_path.write_bytes(_canonical_json_bytes(evidence))
    base_files = (
        "study_manifest.json",
        "ranking_weight_sensitivity.json",
        "validation_report.json",
        "workspace_registry.json",
    )
    registry = {
        "schema_version": "concurrent-robustness-cell-registry-v1",
        "workspace_type": "private_resumable",
        "status": "cells_complete",
        "output_identity": manifest.output_identity,
        "output_root_sha256": hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest(),
        "manifest_sha256": manifest_sha256,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "base_workspace_sha256": {name: _sha256(workspace / name) for name in base_files},
        "cell_evidence": evidence_path.name,
        "cell_evidence_sha256": _sha256(evidence_path),
        "cell_inventory": [
            {
                "cell_id": cell["cell_id"],
                "observed_model": cell["observed_model"],
                "source_identity_sha256": cell["source_identity_sha256"],
                "logical_judgment_count": cell["logical_judgment_count"],
                "physical_attempt_count": cell["physical_attempt_count"],
                "terminal_row_count": len(cast(list[object], cell["terminal_rows"])),
            }
            for cell in cells
        ],
        "logical_judgment_count": logical_per_cell * len(cells),
        "physical_attempt_count": total_physical_attempts,
        "external_request_invocations": 0,
        "production_deploy_eligible": False,
    }
    (workspace / "prompt_model_cell_registry.json").write_bytes(_canonical_json_bytes(registry))
    return evidence


def _rewrite_robustness_cell_fixture(workspace: Path, evidence: dict[str, object]) -> None:
    cells = cast(list[dict[str, object]], evidence["cells"])
    evidence["cell_count"] = len(cells)
    evidence["logical_judgment_count"] = sum(int(cell["logical_judgment_count"]) for cell in cells)
    evidence["physical_attempt_count"] = sum(int(cell["physical_attempt_count"]) for cell in cells)
    evidence_path = workspace / "prompt_model_cell_evidence.json"
    evidence_path.write_bytes(_canonical_json_bytes(evidence))
    registry_path = workspace / "prompt_model_cell_registry.json"
    registry = _read_json(registry_path)
    registry["cell_evidence_sha256"] = _sha256(evidence_path)
    registry["cell_inventory"] = [
        {
            "cell_id": cell["cell_id"],
            "observed_model": cell["observed_model"],
            "source_identity_sha256": cell["source_identity_sha256"],
            "logical_judgment_count": cell["logical_judgment_count"],
            "physical_attempt_count": cell["physical_attempt_count"],
            "terminal_row_count": len(cast(list[object], cell["terminal_rows"])),
        }
        for cell in cells
    ]
    registry["logical_judgment_count"] = evidence["logical_judgment_count"]
    registry["physical_attempt_count"] = evidence["physical_attempt_count"]
    registry_path.write_bytes(_canonical_json_bytes(registry))


def test_concurrent_robustness_complete_result_can_precede_report_candidate(tmp_path: Path) -> None:
    result = ConcurrentRobustnessStudyResult(
        status=ConcurrentRobustnessStudyStatus.COMPLETE,
        workspace_root=tmp_path / "workspace",
        validation_report=tmp_path / "study-root" / "validation_report.json",
        manifest_sha256="a" * 64,
        logical_provider_attempts=96,
        physical_provider_attempts=112,
        study_root=tmp_path / "study-root",
        report_candidate=None,
    )

    assert result.status == ConcurrentRobustnessStudyStatus.COMPLETE
    assert result.study_root == tmp_path / "study-root"
    assert result.report_candidate is None


def test_concurrent_robustness_composes_two_closed_sources_into_an_immutable_report_candidate(
    tmp_path: Path,
) -> None:
    source_dir = _make_validation_report_source(tmp_path, "robustness-report-source")
    manifest = _robustness_manifest_for_source(source_dir, output_identity="fixture-report-v1")
    workspace = tmp_path / "robustness-report-workspace"
    destination = tmp_path / "robustness-report-candidate"
    study = ConcurrentRobustnessStudy()

    study.run(manifest, None, workspace)
    _install_deterministic_robustness_cell_fixture(workspace, manifest)
    complete = study.run(manifest, None, workspace)
    assert complete.study_root is not None
    source_before = {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}
    workspace_before = {path.name: path.read_bytes() for path in workspace.iterdir() if path.is_file()}
    study_before = {path.name: path.read_bytes() for path in complete.study_root.iterdir() if path.is_file()}

    result = study.run(manifest, None, workspace, report_destination=destination)

    assert result.status == ConcurrentRobustnessStudyStatus.COMPLETE
    assert result.report_candidate == destination.resolve()
    assert source_before == {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}
    assert workspace_before == {path.name: path.read_bytes() for path in workspace.iterdir() if path.is_file()}
    assert study_before == {path.name: path.read_bytes() for path in complete.study_root.iterdir() if path.is_file()}
    candidate_manifest = _read_json(destination / "artifact_manifest.json")
    release_evidence = _read_json(destination / "release_evidence.json")
    report_html = (destination / "report.html").read_text(encoding="utf-8")
    assert candidate_manifest["schema_version"] == "concurrent-robustness-report-candidate-manifest-v1"
    assert candidate_manifest["formal_source"]["manifest_sha256"] == manifest.source.manifest_sha256
    assert candidate_manifest["study_source"]["manifest_sha256"] == result.manifest_sha256
    assert candidate_manifest["production_deploy_eligible"] is False
    assert candidate_manifest["row_counts"] == {
        "prompt_model_campaign_growth": 32,
        "prompt_model_message_summary": 48,
        "prompt_model_practical_thresholds": 189,
        "prompt_model_shared_seed_summary": 48,
        "prompt_model_trajectory_summary": 96,
        "ranking_weight_batch_diagnostics": 114,
        "ranking_weight_message_summary": 57,
    }
    assert set(candidate_manifest["artifacts"]) == set(candidate_manifest["sha256"])
    assert set(candidate_manifest["artifacts"].values()) == {
        path.name for path in destination.iterdir() if path.name != "artifact_manifest.json"
    }
    for artifact_name, relative_path in candidate_manifest["artifacts"].items():
        assert _sha256(destination / relative_path) == candidate_manifest["sha256"][artifact_name]
    assert release_evidence["production_deploy_eligible"] is False
    assert release_evidence["provider_calls_during_composition"] == 0
    assert release_evidence["image_generation_triggered"] is False
    assert release_evidence["canonical_deployment_triggered"] is False
    assert not (destination / "prompt_model_cell_evidence.json").exists()
    report_payload = _read_json(destination / "concurrent_robustness_report_payload.json")
    assert report_payload["row_counts"] == candidate_manifest["row_counts"]
    assert report_payload["claim_boundary"] == {
        "below_threshold_label": "small_observed_difference",
        "calibration_claim": False,
        "causal_claim": False,
        "ground_truth_used": False,
        "scope": "fixed_sample_fixed_graph_one_realized_path_per_cell",
        "statistical_equivalence_claim": False,
    }
    with (destination / "ranking_weight_message_summary.csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        weight_rows = list(csv.DictReader(stream))
    assert len(weight_rows) == report_payload["row_counts"]["ranking_weight_message_summary"]
    assert weight_rows[0]["scenario_id"] == report_payload["ranking_weight"]["message_summary_rows"][0][
        "scenario_id"
    ]
    assert weight_rows[0]["message_id"] == report_payload["ranking_weight"]["message_summary_rows"][0][
        "message_id"
    ]
    assert f'<td>{weight_rows[0]["scenario_id"]}</td>' in report_html
    assert f'<td>{weight_rows[0]["message_id"]}</td>' in report_html
    assert all((destination / relative_path).is_file() for relative_path in candidate_manifest["approved_downloads"])
    assert 'data-testid="mechanism-overview-section"' in report_html
    assert 'data-testid="run-evidence-mode-panel"' in report_html
    assert 'data-testid="robustness-source-lineage"' in report_html
    assert 'data-testid="ranking-weight-sensitivity-section"' in report_html
    assert 'data-testid="prompt-model-robustness-section"' in report_html
    assert "Demographic Shadow evidence remains bound to the historical Formal source" in report_html
    assert "production_deploy_eligible=false" in report_html


def test_concurrent_robustness_report_rejects_unsafe_destinations_without_touching_sources(
    tmp_path: Path,
) -> None:
    source_dir = _make_validation_report_source(tmp_path, "robustness-report-path-source")
    manifest = _robustness_manifest_for_source(source_dir, output_identity="fixture-report-path-v1")
    workspace = tmp_path / "robustness-report-path-workspace"
    study = ConcurrentRobustnessStudy()
    study.run(manifest, None, workspace)
    _install_deterministic_robustness_cell_fixture(workspace, manifest)
    complete = study.run(manifest, None, workspace)
    assert complete.study_root is not None
    source_before = {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}
    workspace_before = {path.name: path.read_bytes() for path in workspace.iterdir() if path.is_file()}
    study_before = {path.name: path.read_bytes() for path in complete.study_root.iterdir() if path.is_file()}

    existing = tmp_path / "nonempty-report-candidate"
    existing.mkdir()
    sentinel = existing / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    symlink_target = tmp_path / "report-candidate-link-target"
    symlink_target.mkdir()
    symlink_destination = tmp_path / "report-candidate-link"
    os.symlink(symlink_target, symlink_destination, target_is_directory=True)
    destinations = (
        (source_dir / "nested-report", ConcurrentRobustnessErrorCode.PATH_VIOLATION),
        (workspace / "nested-report", ConcurrentRobustnessErrorCode.PATH_VIOLATION),
        (complete.study_root / "nested-report", ConcurrentRobustnessErrorCode.PATH_VIOLATION),
        (tmp_path / ".." / "escaped-report", ConcurrentRobustnessErrorCode.PATH_VIOLATION),
        (existing, ConcurrentRobustnessErrorCode.WORKSPACE_CONFLICT),
        (symlink_destination, ConcurrentRobustnessErrorCode.WORKSPACE_CONFLICT),
    )
    for destination, expected_code in destinations:
        with pytest.raises(ConcurrentRobustnessError) as captured:
            study.run(manifest, None, workspace, report_destination=destination)
        assert captured.value.code == expected_code

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert source_before == {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}
    assert workspace_before == {path.name: path.read_bytes() for path in workspace.iterdir() if path.is_file()}
    assert study_before == {path.name: path.read_bytes() for path in complete.study_root.iterdir() if path.is_file()}
    assert not list(tmp_path.glob(".*.staging"))


def test_concurrent_robustness_report_cleans_staging_when_candidate_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = _make_validation_report_source(tmp_path, "robustness-report-failure-source")
    manifest = _robustness_manifest_for_source(source_dir, output_identity="fixture-report-failure-v1")
    workspace = tmp_path / "robustness-report-failure-workspace"
    destination = tmp_path / "robustness-report-failure-candidate"
    study = ConcurrentRobustnessStudy()
    study.run(manifest, None, workspace)
    _install_deterministic_robustness_cell_fixture(workspace, manifest)
    complete = study.run(manifest, None, workspace)
    assert complete.study_root is not None
    source_before = {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}
    workspace_before = {path.name: path.read_bytes() for path in workspace.iterdir() if path.is_file()}
    study_before = {path.name: path.read_bytes() for path in complete.study_root.iterdir() if path.is_file()}

    def fail_candidate_validation(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise concurrent_robustness_report_module._RobustnessReportClosureError("injected validation failure")

    monkeypatch.setattr(concurrent_robustness_report_module, "_validate_candidate", fail_candidate_validation)
    with pytest.raises(ConcurrentRobustnessError) as captured:
        study.run(manifest, None, workspace, report_destination=destination)

    assert captured.value.code == ConcurrentRobustnessErrorCode.ANALYSIS_INVALID
    assert not destination.exists()
    assert not list(tmp_path.glob(f".{destination.name}.*.staging"))
    assert source_before == {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}
    assert workspace_before == {path.name: path.read_bytes() for path in workspace.iterdir() if path.is_file()}
    assert study_before == {path.name: path.read_bytes() for path in complete.study_root.iterdir() if path.is_file()}


@pytest.mark.parametrize("corruption", ["missing", "extra", "mutated", "crossed", "symlink"])
def test_concurrent_robustness_report_rejects_corrupt_study_root_before_candidate(
    tmp_path: Path,
    corruption: str,
) -> None:
    source_dir = _make_validation_report_source(tmp_path, f"robustness-report-{corruption}-source")
    manifest = _robustness_manifest_for_source(
        source_dir,
        output_identity=f"fixture-report-{corruption}-v1",
    )
    workspace = tmp_path / f"robustness-report-{corruption}-workspace"
    destination = tmp_path / f"robustness-report-{corruption}-candidate"
    study = ConcurrentRobustnessStudy()
    study.run(manifest, None, workspace)
    _install_deterministic_robustness_cell_fixture(workspace, manifest)
    complete = study.run(manifest, None, workspace)
    assert complete.study_root is not None

    if corruption == "missing":
        (complete.study_root / "claim_audit.json").unlink()
    elif corruption == "extra":
        (complete.study_root / "unexpected.json").write_text("{}\n", encoding="utf-8")
    elif corruption == "mutated":
        analysis_path = complete.study_root / "prompt_model_analysis.json"
        analysis_path.write_bytes(analysis_path.read_bytes() + b" ")
    elif corruption == "crossed":
        (complete.study_root / "prompt_model_analysis.json").write_bytes(
            (complete.study_root / "ranking_weight_sensitivity.json").read_bytes()
        )
    else:
        claims_path = complete.study_root / "claim_audit.json"
        claims_copy = tmp_path / "crossed-claim-audit.json"
        claims_copy.write_bytes(claims_path.read_bytes())
        claims_path.unlink()
        os.symlink(claims_copy, claims_path)

    with pytest.raises(ConcurrentRobustnessError) as captured:
        study.run(manifest, None, workspace, report_destination=destination)

    assert captured.value.code == ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT
    assert not destination.exists()
    assert not list(tmp_path.glob(f".{destination.name}.*.staging"))


def test_concurrent_robustness_report_rejects_changed_formal_source_before_candidate(tmp_path: Path) -> None:
    source_dir = _make_validation_report_source(tmp_path, "robustness-report-formal-mutation-source")
    manifest = _robustness_manifest_for_source(source_dir, output_identity="fixture-report-formal-mutation-v1")
    workspace = tmp_path / "robustness-report-formal-mutation-workspace"
    destination = tmp_path / "robustness-report-formal-mutation-candidate"
    study = ConcurrentRobustnessStudy()
    study.run(manifest, None, workspace)
    _install_deterministic_robustness_cell_fixture(workspace, manifest)
    study.run(manifest, None, workspace)
    unexpected = source_dir / "unexpected-source-artifact.json"
    unexpected.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ConcurrentRobustnessError) as captured:
        study.run(manifest, None, workspace, report_destination=destination)

    assert captured.value.code == ConcurrentRobustnessErrorCode.INVALID_SOURCE
    assert not destination.exists()
    assert not list(tmp_path.glob(f".{destination.name}.*.staging"))


def test_concurrent_robustness_closes_deterministic_cell_evidence_through_resume_path(tmp_path: Path) -> None:
    source_dir = _make_validation_report_source(tmp_path, "robustness-analysis-source")
    manifest = _robustness_manifest_for_source(source_dir, output_identity="fixture-analysis-v1")
    workspace = tmp_path / "robustness-analysis-workspace"
    study = ConcurrentRobustnessStudy()

    ready = study.run(manifest, None, workspace)
    assert ready.status == ConcurrentRobustnessStudyStatus.READY_FOR_HUMAN
    _install_deterministic_robustness_cell_fixture(workspace, manifest)
    workspace_before = {
        path.name: path.read_bytes()
        for path in workspace.iterdir()
        if path.is_file()
    }

    result = study.run(manifest, None, workspace)

    assert result.status == ConcurrentRobustnessStudyStatus.COMPLETE
    assert result.workspace_root == workspace.resolve()
    assert result.study_root == workspace.with_name(f"{workspace.name}.study-root").resolve()
    assert result.report_candidate is None
    assert result.logical_provider_attempts == manifest.request_caps.logical_judgment_cap == 960
    assert result.physical_provider_attempts == 962
    assert workspace_before == {path.name: path.read_bytes() for path in workspace.iterdir() if path.is_file()}
    assert result.study_root is not None
    assert {path.name for path in result.study_root.iterdir()} == {
        "artifact_manifest.json",
        "claim_audit.json",
        "prompt_model_analysis.json",
        "prompt_model_cell_evidence.json",
        "ranking_weight_sensitivity.json",
        "study_manifest.json",
        "validation_report.json",
    }

    analysis = _read_json(result.study_root / "prompt_model_analysis.json")
    validation = _read_json(result.study_root / "validation_report.json")
    claim_audit = _read_json(result.study_root / "claim_audit.json")
    root_manifest = _read_json(result.study_root / "artifact_manifest.json")
    assert analysis["schema_version"] == "concurrent-prompt-model-robustness-analysis-v1"
    assert analysis["shared_seed_direct_decisions"]["primary_outcome"] == "binary_engage"
    assert analysis["shared_seed_direct_decisions"]["fixed_pair_count"] == 30
    assert analysis["shared_seed_direct_decisions"]["complete_decision_pair_count"] == 30
    assert analysis["fixed_factor_summaries"]["factor_types"] == {
        "message": "fixed_categorical",
        "model": "fixed_categorical",
        "prompt": "fixed_categorical",
    }
    assert analysis["fixed_factor_summaries"]["linear_model_version_trend_computed"] is False
    assert [row["contrast_id"] for row in analysis["fixed_factor_summaries"]["planned_model_contrasts"]] == [
        "gpt-5.4-mini_vs_gpt-5.4",
        "gpt-5.4_vs_gpt-5.5",
        "gpt-5.5_vs_gpt-5.6-sol",
    ]
    assert analysis["bootstrap"]["block"] == "user_with_all_three_messages"
    assert analysis["bootstrap"]["conditional_scope"] == (
        "fixed_sample_fixed_graph_one_realized_path_per_cell"
    )
    failed_message = next(
        row
        for row in analysis["realized_paths"]["message_summaries"]
        if row["cell_id"] == manifest.prompt_model_cells[1].cell_id and row["message_id"] == "message_3"
    )
    assert failed_message["actual_exposures"] == 20
    assert failed_message["successful_primary_decisions"] == 19
    assert failed_message["provider_failures"] == 1
    assert failed_message["exposure_engagement_rate"] == pytest.approx(
        failed_message["positive_actions"] / 20
    )
    assert failed_message["decision_engagement_rate"] == pytest.approx(
        failed_message["positive_actions"] / 19
    )
    fixture_evidence = _read_json(workspace / "prompt_model_cell_evidence.json")
    failed_cell = cast(list[dict[str, object]], fixture_evidence["cells"])[1]
    successful_probabilities = [
        float(row["probability"])
        for row in cast(list[dict[str, object]], failed_cell["terminal_rows"])
        if row["message_id"] == "message_3" and row["terminal_status"] == "succeeded"
    ]
    assert failed_message["mean_probability_successful_decisions"] == pytest.approx(
        sum(successful_probabilities) / len(successful_probabilities)
    )
    assert failed_message["first_divergent_batch_from_baseline_cell"] == 1
    assert failed_message["terminal_audience_overlap_count_with_baseline_cell"] < 20
    accounting_cell = analysis["provider_accounting"]["cells"][1]
    assert accounting_cell["logical_judgments"] == 60
    assert accounting_cell["physical_attempts"] == 62
    assert accounting_cell["provider_failures"] == 1
    assert analysis["practical_thresholds"]["terminal_positive_users_production_count"] == 50
    assert analysis["practical_thresholds"]["terminal_positive_users_manifest_count"] == 2
    assert all(
        row["classification"] in {"practically_meaningful", "small_observed_difference"}
        for row in analysis["practical_threshold_classifications"]
    )
    assert claim_audit["status"] == "passed"
    assert claim_audit["conditional_intervals"] is True
    assert validation["status"] == "complete"
    assert validation["counts"]["production_contract_logical_judgments"] == 28_800
    assert validation["counts"]["manifest_logical_judgments"] == 960
    assert validation["checks"]["provider_failures_excluded_from_decision_denominator"] is True
    assert root_manifest["root_type"] == "immutable_closed_study"
    for relative_path, expected_hash in root_manifest["sha256"].items():
        assert _sha256(result.study_root / relative_path) == expected_hash

    root_before_resume = {path.name: path.read_bytes() for path in result.study_root.iterdir()}
    resumed = study.run(manifest, None, workspace)
    assert resumed == result
    assert root_before_resume == {path.name: path.read_bytes() for path in result.study_root.iterdir()}


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_cell",
        "extra_cell",
        "duplicate_pair",
        "mixed_observed_model",
        "crossed_prompt_hash",
        "crossed_request_contract",
        "crossed_source_identity",
        "forbidden_claim",
        "missing_terminal",
        "physical_accounting",
    ],
)
def test_concurrent_robustness_cell_contract_fails_closed_before_study_root(
    tmp_path: Path,
    corruption: str,
) -> None:
    source_dir = _make_validation_report_source(tmp_path, f"robustness-cell-{corruption}-source")
    manifest = _robustness_manifest_for_source(source_dir, output_identity=f"fixture-{corruption}-v1")
    workspace = tmp_path / f"robustness-cell-{corruption}-workspace"
    study = ConcurrentRobustnessStudy()
    study.run(manifest, None, workspace)
    evidence = _install_deterministic_robustness_cell_fixture(workspace, manifest)
    cells = cast(list[dict[str, object]], evidence["cells"])

    if corruption == "missing_cell":
        cells.pop()
    elif corruption == "extra_cell":
        extra_cell = json.loads(json.dumps(cells[-1]))
        extra_cell["cell_index"] = 16
        extra_cell["cell_id"] = "extra-cell"
        cells.append(extra_cell)
    elif corruption == "duplicate_pair":
        terminal_rows = cast(list[dict[str, object]], cells[0]["terminal_rows"])
        terminal_rows[1]["pair_id"] = terminal_rows[0]["pair_id"]
        terminal_rows[1]["terminal_row_id"] = terminal_rows[0]["terminal_row_id"]
        terminal_rows[1]["user_id"] = terminal_rows[0]["user_id"]
    elif corruption == "mixed_observed_model":
        terminal_rows = cast(list[dict[str, object]], cells[0]["terminal_rows"])
        terminal_rows[0]["observed_model_counts"] = {"gpt-crossed-observed-model": 1}
    elif corruption == "crossed_prompt_hash":
        cells[0]["prompt_canonical_hash"] = "sha256:" + "0" * 64
    elif corruption == "crossed_request_contract":
        evidence["request_contract_sha256"] = "0" * 64
    elif corruption == "crossed_source_identity":
        cast(dict[str, object], evidence["source_identity"])["sample_identity"] = "0" * 64
    elif corruption == "forbidden_claim":
        cast(list[str], evidence["claim_statements"])[0] = "This establishes a causal effect."
    elif corruption == "missing_terminal":
        terminal_rows = cast(list[dict[str, object]], cells[0]["terminal_rows"])
        removed = terminal_rows.pop()
        cells[0]["logical_judgment_count"] = len(terminal_rows)
        cells[0]["physical_attempt_count"] = int(cells[0]["physical_attempt_count"]) - int(
            cast(dict[str, object], removed)["request_invocations"]
        )
    else:
        cells[0]["physical_attempt_count"] = int(cells[0]["physical_attempt_count"]) + 1

    _rewrite_robustness_cell_fixture(workspace, evidence)

    with pytest.raises(ConcurrentRobustnessError) as captured:
        study.run(manifest, None, workspace)
    assert captured.value.code == ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT
    assert not workspace.with_name(f"{workspace.name}.study-root").exists()


@pytest.mark.parametrize("corruption", ["mutated", "extra", "symlink"])
def test_concurrent_robustness_closed_root_is_immutable_and_hash_closed(
    tmp_path: Path,
    corruption: str,
) -> None:
    source_dir = _make_validation_report_source(tmp_path, f"robustness-root-{corruption}-source")
    manifest = _robustness_manifest_for_source(source_dir, output_identity=f"fixture-root-{corruption}-v1")
    workspace = tmp_path / f"robustness-root-{corruption}-workspace"
    study = ConcurrentRobustnessStudy()
    study.run(manifest, None, workspace)
    _install_deterministic_robustness_cell_fixture(workspace, manifest)
    result = study.run(manifest, None, workspace)
    assert result.study_root is not None
    workspace_before = {path.name: path.read_bytes() for path in workspace.iterdir()}

    if corruption == "mutated":
        analysis_path = result.study_root / "prompt_model_analysis.json"
        analysis_path.write_bytes(analysis_path.read_bytes() + b" ")
    elif corruption == "extra":
        (result.study_root / "unexpected.json").write_text("{}\n", encoding="utf-8")
    else:
        claims_path = result.study_root / "claim_audit.json"
        claims_copy = tmp_path / "claims-copy.json"
        claims_copy.write_bytes(claims_path.read_bytes())
        claims_path.unlink()
        os.symlink(claims_copy, claims_path)

    with pytest.raises(ConcurrentRobustnessError) as captured:
        study.run(manifest, None, workspace)
    assert captured.value.code == ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT
    assert workspace_before == {path.name: path.read_bytes() for path in workspace.iterdir()}
    assert not any(path.name.endswith(".staging") for path in tmp_path.iterdir())


def test_concurrent_robustness_closed_root_cannot_overlap_formal_source(tmp_path: Path) -> None:
    workspace = tmp_path / "robustness-overlap-workspace"
    source_dir = _make_validation_report_source(tmp_path, f"{workspace.name}.study-root")
    manifest = _robustness_manifest_for_source(source_dir, output_identity="fixture-root-overlap-v1")
    study = ConcurrentRobustnessStudy()
    study.run(manifest, None, workspace)
    _install_deterministic_robustness_cell_fixture(workspace, manifest)
    source_before = {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}

    with pytest.raises(ConcurrentRobustnessError) as captured:
        study.run(manifest, None, workspace)

    assert captured.value.code == ConcurrentRobustnessErrorCode.PATH_VIOLATION
    assert source_before == {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}


def test_concurrent_robustness_manifest_rejects_noncanonical_weights_and_cells(tmp_path: Path) -> None:
    source_dir = _make_validation_report_source(tmp_path, "robustness-manifest-source")
    manifest = _robustness_manifest_for_source(source_dir, output_identity="fixture-manifest-v1")
    payload = manifest.model_dump(mode="json")

    missing_weight = json.loads(json.dumps(payload))
    missing_weight["weight_points"].pop()
    with pytest.raises(ValueError, match="19 canonical weight points"):
        ConcurrentRobustnessManifest.model_validate(missing_weight)

    non_finite_weight = json.loads(json.dumps(payload))
    non_finite_weight["weight_points"][0]["weights"]["base_network_relevance"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        ConcurrentRobustnessManifest.model_validate(non_finite_weight)

    changed_sum = json.loads(json.dumps(payload))
    changed_sum["weight_points"][0]["weights"]["base_network_relevance"] = 0.51
    with pytest.raises(ValueError, match="unit sum"):
        ConcurrentRobustnessManifest.model_validate(changed_sum)

    missing_cell = json.loads(json.dumps(payload))
    missing_cell["prompt_model_cells"].pop()
    with pytest.raises(ValueError, match="16 canonical Prompt-Model cells"):
        ConcurrentRobustnessManifest.model_validate(missing_cell)

    partial_observed_contract = json.loads(json.dumps(payload))
    partial_observed_contract["prompt_model_cells"][0]["required_observed_model"] = None
    with pytest.raises(ValueError, match="observed-model contract must cover all 16"):
        ConcurrentRobustnessManifest.model_validate(partial_observed_contract)

    mixed_observed_contract = json.loads(json.dumps(payload))
    mixed_observed_contract["prompt_model_cells"][4]["required_observed_model"] = "gpt-crossed-model"
    with pytest.raises(ValueError, match="mixed required observed identities"):
        ConcurrentRobustnessManifest.model_validate(mixed_observed_contract)

    static_v1_payload = json.loads(json.dumps(payload))
    for cell in static_v1_payload["prompt_model_cells"]:
        cell.pop("required_observed_model")
    static_v1_manifest = ConcurrentRobustnessManifest.model_validate(static_v1_payload)
    assert all(cell.required_observed_model is None for cell in static_v1_manifest.prompt_model_cells)


def test_concurrent_robustness_static_study_is_offline_hashed_and_resumable(tmp_path: Path) -> None:
    source_dir = _make_validation_report_source(tmp_path, "robustness-static-source")
    manifest = _robustness_manifest_for_source(source_dir, output_identity="fixture-static-v1")
    output_dir = tmp_path / "robustness-static-workspace"
    source_before = {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}

    class NeverCalledAdapter:
        calls = 0

        def decide(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            self.calls += 1
            raise AssertionError("static robustness must not call an Adapter")

    adapter = NeverCalledAdapter()
    study = ConcurrentRobustnessStudy()
    with pytest.raises(ConcurrentRobustnessError) as nonempty_error:
        study.run(manifest, {"unexpected": cast(LLMDecisionAdapter, adapter)}, output_dir)
    assert nonempty_error.value.code == ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS
    with pytest.raises(ConcurrentRobustnessError) as empty_error:
        study.run(manifest, {}, output_dir)
    assert empty_error.value.code == ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS
    assert adapter.calls == 0
    assert not output_dir.exists()
    premature_candidate = tmp_path / "premature-report-candidate"
    with pytest.raises(ConcurrentRobustnessError) as premature_error:
        study.run(manifest, None, output_dir, report_destination=premature_candidate)
    assert premature_error.value.code == ConcurrentRobustnessErrorCode.ANALYSIS_INVALID
    assert not output_dir.exists()
    assert not premature_candidate.exists()

    dataset_dir = Path(str(close_concurrent_message_artifacts(source_dir).source_evidence.config_snapshot["dataset_dir"]))
    dataset_dir.rename(tmp_path / "processed-source-moved-away")

    result = study.run(manifest, None, output_dir)

    assert result.status == ConcurrentRobustnessStudyStatus.READY_FOR_HUMAN
    assert result.workspace_root == output_dir.resolve()
    assert result.validation_report == output_dir.resolve() / "validation_report.json"
    assert result.logical_provider_attempts == 0
    assert result.physical_provider_attempts == 0
    assert result.study_root is None
    assert result.report_candidate is None
    assert set(path.name for path in output_dir.iterdir()) == {
        "study_manifest.json",
        "ranking_weight_sensitivity.json",
        "validation_report.json",
        "workspace_registry.json",
    }
    assert not (output_dir / "report.html").exists()
    assert source_before == {path.name: path.read_bytes() for path in source_dir.iterdir() if path.is_file()}

    analysis = _read_json(output_dir / "ranking_weight_sensitivity.json")
    validation = _read_json(output_dir / "validation_report.json")
    registry = _read_json(output_dir / "workspace_registry.json")
    assert analysis["schema_version"] == "concurrent-ranking-weight-sensitivity-v1"
    assert analysis["counts"] == {
        "scenario_count": 19,
        "message_count": 3,
        "batch_count_per_message": 2,
        "scenario_message_batch_count": 19 * 3 * 2,
    }
    assert analysis["logical_provider_attempts"] == 0
    assert analysis["physical_provider_attempts"] == 0
    baseline = analysis["scenarios"][0]
    assert baseline["scenario_id"] == "baseline"
    assert baseline["baseline_reproduced"] is True
    for message in baseline["messages"]:
        assert message["first_divergent_batch"] is None
        assert message["curve_mean_jaccard_distance"] == 0.0
        assert message["curve_auc_jaccard_distance"] == 0.0
        for batch in message["batches"]:
            assert batch["baseline_top_user_ids"] == batch["scenario_top_user_ids"]
            assert batch["jaccard_distance"] == 0.0
            assert batch["entered_user_ids"] == []
            assert batch["exited_user_ids"] == []
            assert batch["first_divergent_rank"] is None

    inspected_batch = analysis["scenarios"][-1]["messages"][0]["batches"][0]
    baseline_top = set(inspected_batch["baseline_top_user_ids"])
    scenario_top = set(inspected_batch["scenario_top_user_ids"])
    expected_distance = 1.0 - len(baseline_top & scenario_top) / len(baseline_top | scenario_top)
    assert inspected_batch["jaccard_distance"] == pytest.approx(expected_distance)
    for rank_delta in inspected_batch["rank_deltas"]:
        assert rank_delta["rank_delta"] == rank_delta["scenario_rank"] - rank_delta["baseline_rank"]

    assert validation["status"] == "ready_for_human"
    assert validation["checks"]["baseline_reproduced"] is True
    assert validation["checks"]["source_unchanged"] is True
    assert validation["checks"]["provider_attempts_zero"] is True
    assert validation["production_deploy_eligible"] is False
    assert registry["workspace_type"] == "private_resumable"
    assert registry["status"] == "ready_for_human"
    assert registry["production_deploy_eligible"] is False
    assert registry["study_root"] is None
    assert registry["report_candidate"] is None
    assert registry["logical_provider_attempts"] == 0
    assert registry["physical_provider_attempts"] == 0
    for artifact_name, relative_path in registry["artifacts"].items():
        assert registry["sha256"][artifact_name] == _sha256(output_dir / relative_path)

    workspace_before_resume = {path.name: path.read_bytes() for path in output_dir.iterdir()}
    resumed = study.run(manifest, None, output_dir)
    assert resumed == result
    assert workspace_before_resume == {path.name: path.read_bytes() for path in output_dir.iterdir()}


def test_concurrent_robustness_rejects_crossed_mutated_and_unsafe_evidence(tmp_path: Path) -> None:
    source_dir = _make_validation_report_source(tmp_path, "robustness-security-source")
    manifest = _robustness_manifest_for_source(source_dir, output_identity="fixture-security-v1")
    output_dir = tmp_path / "robustness-security-workspace"
    study = ConcurrentRobustnessStudy()
    study.run(manifest, None, output_dir)

    def assert_error_code(
        expected_code: ConcurrentRobustnessErrorCode,
        active_manifest: ConcurrentRobustnessManifest = manifest,
        active_output: Path = output_dir,
    ) -> None:
        with pytest.raises(ConcurrentRobustnessError) as captured:
            study.run(active_manifest, None, active_output)
        assert captured.value.code == expected_code

    extra_path = output_dir / "unexpected.json"
    extra_path.write_text("{}\n", encoding="utf-8")
    assert_error_code(ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT)
    extra_path.unlink()

    validation_path = output_dir / "validation_report.json"
    validation_bytes = validation_path.read_bytes()
    validation_path.unlink()
    assert_error_code(ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT)
    validation_path.write_bytes(validation_bytes)

    analysis_path = output_dir / "ranking_weight_sensitivity.json"
    analysis_bytes = analysis_path.read_bytes()
    analysis_path.write_bytes(analysis_bytes + b" ")
    assert_error_code(ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT)
    analysis_path.write_bytes(analysis_bytes)

    symlink_target = tmp_path / "crossed-analysis.json"
    symlink_target.write_bytes(analysis_bytes)
    analysis_path.unlink()
    os.symlink(symlink_target, analysis_path)
    assert_error_code(ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT)
    analysis_path.unlink()
    analysis_path.write_bytes(analysis_bytes)

    registry_path = output_dir / "workspace_registry.json"
    registry_bytes = registry_path.read_bytes()
    registry = _read_json(registry_path)
    registry["artifacts"]["weight_sensitivity"] = "../ranking_weight_sensitivity.json"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    assert_error_code(ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT)
    registry_path.write_bytes(registry_bytes)

    validation_bytes = validation_path.read_bytes()
    analysis_document = _read_json(analysis_path)
    analysis_document["scenarios"][-1]["overall_mean_jaccard_distance"] = 0.987654321
    analysis_path.write_text(
        json.dumps(analysis_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    validation_document = _read_json(validation_path)
    validation_document["ranking_weight_sensitivity_sha256"] = _sha256(analysis_path)
    validation_path.write_text(
        json.dumps(validation_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    registry_document = _read_json(registry_path)
    registry_document["sha256"]["weight_sensitivity"] = _sha256(analysis_path)
    registry_document["sha256"]["validation_report"] = _sha256(validation_path)
    registry_path.write_text(
        json.dumps(registry_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    assert_error_code(ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT)
    analysis_path.write_bytes(analysis_bytes)
    validation_path.write_bytes(validation_bytes)
    registry_path.write_bytes(registry_bytes)

    crossed_payload = manifest.model_dump(mode="json")
    crossed_payload["output_identity"] = "fixture-security-crossed-v1"
    crossed_manifest = ConcurrentRobustnessManifest.model_validate(crossed_payload)
    assert_error_code(ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT, crossed_manifest)

    source_extra = source_dir / "unexpected-source.json"
    source_extra.write_text("{}\n", encoding="utf-8")
    assert_error_code(ConcurrentRobustnessErrorCode.INVALID_SOURCE)
    source_extra.unlink()

    candidate_path = source_dir / "concurrent_runtime_candidates.csv"
    candidate_bytes = candidate_path.read_bytes()
    candidate_path.write_bytes(candidate_bytes + b"\n")
    assert_error_code(ConcurrentRobustnessErrorCode.INVALID_SOURCE)
    candidate_path.write_bytes(candidate_bytes)

    assert_error_code(
        ConcurrentRobustnessErrorCode.PATH_VIOLATION,
        active_output=source_dir / "nested-workspace",
    )

    source_link = tmp_path / "robustness-source-link"
    os.symlink(source_dir, source_link, target_is_directory=True)
    linked_payload = manifest.model_dump(mode="json")
    linked_payload["source"]["source_dir"] = str(source_link)
    linked_payload["source"]["source_id"] = source_link.name
    linked_manifest = ConcurrentRobustnessManifest.model_validate(linked_payload)
    assert_error_code(
        ConcurrentRobustnessErrorCode.PATH_VIOLATION,
        linked_manifest,
        tmp_path / "linked-source-workspace",
    )

    output_link = tmp_path / "robustness-output-link"
    os.symlink(output_dir, output_link, target_is_directory=True)
    assert_error_code(
        ConcurrentRobustnessErrorCode.PATH_VIOLATION,
        active_output=output_link,
    )

    unrelated_output = tmp_path / "unrelated-existing-output"
    unrelated_output.mkdir()
    (unrelated_output / "unrelated.txt").write_text("not a workspace", encoding="utf-8")
    assert_error_code(
        ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
        active_output=unrelated_output,
    )


def test_concurrent_robustness_validates_explicit_existing_formal_fixture_offline(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source_dir = repository_root / "runs" / "jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z"
    if not source_dir.is_dir():
        pytest.skip("explicit ignored Formal fixture is not available in this checkout")
    manifest = _robustness_manifest_for_source(source_dir, output_identity="formal-static-verification-v1")

    result = ConcurrentRobustnessStudy().run(manifest, None, tmp_path / "formal-robustness-workspace")

    analysis = _read_json(result.workspace_root / "ranking_weight_sensitivity.json")
    assert result.status == ConcurrentRobustnessStudyStatus.READY_FOR_HUMAN
    assert analysis["counts"] == {
        "scenario_count": 19,
        "message_count": 3,
        "batch_count_per_message": 30,
        "scenario_message_batch_count": 19 * 3 * 30,
    }
    assert analysis["scenarios"][0]["baseline_reproduced"] is True
    changed_batches = [
        batch
        for scenario in analysis["scenarios"][1:]
        for message in scenario["messages"]
        for batch in message["batches"]
        if batch["jaccard_distance"] > 0.0
    ]
    assert changed_batches
    assert all(batch["entered_user_ids"] and batch["exited_user_ids"] for batch in changed_batches)
    assert result.logical_provider_attempts == 0
    assert result.physical_provider_attempts == 0
