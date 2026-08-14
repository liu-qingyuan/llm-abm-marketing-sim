from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import llm_abm_sim
import llm_abm_sim.full_pool_formal_experiment as full_pool_module
from llm_abm_sim.decision import DecisionInput, EngageDecision, LLMDecisionAdapter, ProviderDecisionError
from llm_abm_sim.final_research import TARGET_VIDEO_ID
from llm_abm_sim.full_pool_formal_experiment import (
    FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256,
    FULL_POOL_CONTRACT_SCHEMA,
    FULL_POOL_PRODUCTION_CANDIDATE_ROWS,
    FULL_POOL_PRODUCTION_CAPACITY,
    FULL_POOL_PRODUCTION_DATASET_IDENTITY,
    FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
    FULL_POOL_PRODUCTION_FINAL_BATCH_PAIRS_PER_MESSAGE,
    FULL_POOL_PRODUCTION_HORIZON,
    FULL_POOL_PRODUCTION_USER_COUNT,
    FULL_POOL_PRODUCTION_USER_IDS_SHA256,
    FULL_POOL_PRODUCTION_USER_SET_IDENTITY,
    FULL_POOL_VALIDATION_DATASET_IDENTITY,
    FULL_POOL_VALIDATION_TOKEN,
    FullPoolExperimentContract,
    FullPoolExperimentError,
    FullPoolExperimentErrorCode,
    FullPoolFormalExperiment,
    FullPoolRunStatus,
)
from llm_abm_sim.prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fixture_dataset(tmp_path: Path, *, user_count: int = 7) -> Path:
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
                "caption": "holdout",
                "hashtags": "[]",
                "creator_user_id": "target-creator",
                "like_count": 0,
                "comment_count": 0,
                "share_count": 0,
                "collect_count": 0,
            },
            {
                "video_id": "historical-video",
                "source_challenge_name": "锦江酒店",
                "source_challenge_rank": 3,
                "video_url": "https://example.test/history",
                "caption": "history",
                "hashtags": "[]",
                "creator_user_id": "history-creator",
                "like_count": 0,
                "comment_count": 0,
                "share_count": 0,
                "collect_count": 0,
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
                "comment_id": f"history-{number}",
                "video_id": "historical-video",
                "parent_comment_id": "0",
                "commenter_user_id": f"u{number}",
                "mentioned_user_ids": json.dumps(["u1"] if number > 1 else ["u2"]),
                "like_count": 20 - number,
                "comment_level": "comment",
            }
            for number in range(1, user_count + 1)
        ],
    )
    latent_fields = [
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
    _write_csv(
        dataset_dir / "users.csv",
        [
            "user_id",
            "nickname",
            "bio",
            "signature",
            "follower_count",
            "following_count",
            "video_count",
            "global_influence_score",
            *latent_fields,
        ],
        [
            {
                "user_id": f"u{number}",
                "nickname": f"User {number}",
                "bio": "",
                "signature": "",
                "follower_count": 1000 - number,
                "following_count": 10 + number,
                "video_count": 20 - number,
                "global_influence_score": 1000 - number,
                "latent_attribute_spec_id": "fixture-latent-v1",
                "latent_attribute_method": "fixture-exact",
                "latent_attribute_seed": 7,
                "latent_class": f"class_{((number - 1) % 3) + 1}",
                "latent_environmental_consciousness_coef": 1.0,
                "latent_epistemic_value_weight": float(number % 3 + 1),
                "latent_environmental_value_weight": 2.0,
                "latent_functional_value_weight": 1.0,
                "latent_health_value_weight": 2.0,
                "latent_emotional_value_weight": 1.0,
                "latent_social_value_weight": 1.0,
                "latent_hotel_class": "midscale",
                "latent_travel_purpose": "leisure",
                "latent_gender": "female",
                "latent_age": "age_26_35",
                "latent_education": "bachelor",
                "latent_monthly_income": "income_8001_15000",
            }
            for number in range(1, user_count + 1)
        ],
    )
    return dataset_dir


def _user_set_sha256(dataset_dir: Path) -> str:
    with (dataset_dir / "users.csv").open(encoding="utf-8", newline="") as handle:
        user_ids = sorted(str(row["user_id"]).strip() for row in csv.DictReader(handle))
    payload = json.dumps(user_ids, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _DeterministicPrimaryAdapter(LLMDecisionAdapter):
    prompt_version = CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    external_request_invocations = 0

    def __init__(self) -> None:
        self.request_invocations = 0
        self.calls: list[tuple[int, str, str]] = []
        self.safe_metadata = {
            "adapter": "full_pool_validation_fixture",
            "provider": "deterministic",
            "model": "deterministic-primary-v1",
            "prompt_version": self.prompt_version,
        }

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        self.request_invocations += 1
        self.calls.append((time_step, post.post_id, profile.user_id))
        DecisionInput(
            post=post,
            profile=profile,
            peer_context=peer_context,
            platform_context=platform_context or PlatformContext(),
            time_step=time_step,
            prompt_version=self.prompt_version,
        )
        positive = time_step == 0 and profile.user_id == "u1"
        return EngageDecision(
            engage=positive,
            probability=0.9 if positive else 0.1,
            reason="deterministic validation",
            confidence=0.9,
            action="like" if positive else "ignore",
            decision_source="full_pool_validation_fixture",
            provider_metadata={"adapter": "full_pool_validation_fixture", "model": "deterministic-primary-v1"},
        )


class _ProviderFailurePrimaryAdapter(_DeterministicPrimaryAdapter):
    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        if time_step == 0 and profile.user_id == "u2":
            self.request_invocations += 1
            self.calls.append((time_step, post.post_id, profile.user_id))
            raise ProviderDecisionError(TimeoutError("deterministic provider failure"))
        return super().decide(post, profile, peer_context, platform_context, time_step)


class _ExternalRequestPrimaryAdapter(_DeterministicPrimaryAdapter):
    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        self.external_request_invocations += 1
        return super().decide(post, profile, peer_context, platform_context, time_step)


def _contract(dataset_dir: Path, *, output_identity: str) -> FullPoolExperimentContract:
    user_count = 7
    horizon = 3
    capacity = 3
    expected_pairs = user_count * 3
    expected_candidates = 3 * (horizon * user_count - capacity * horizon * (horizon - 1) // 2)
    return FullPoolExperimentContract(
        schema_version=FULL_POOL_CONTRACT_SCHEMA,
        profile="deterministic_validation",
        validation_token=FULL_POOL_VALIDATION_TOKEN,
        dataset_dir=dataset_dir,
        dataset_identity=FULL_POOL_VALIDATION_DATASET_IDENTITY,
        eligible_user_set_identity="full-pool-validation-eligible-users-v1",
        eligible_user_ids_sha256=_user_set_sha256(dataset_dir),
        eligible_user_count=user_count,
        message_ids=("message_1", "message_2", "message_3"),
        message_snapshot_sha256=FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256,
        horizon=horizon,
        per_message_capacity=capacity,
        seed_top_k_per_proxy=2,
        primary_only=True,
        expected_eligible_pairs=expected_pairs,
        expected_exposures=expected_pairs,
        expected_primary_terminals=expected_pairs,
        expected_committed_batches=horizon,
        expected_candidate_ranking_rows=expected_candidates,
        expected_final_batch_pairs_per_message=1,
        output_identity=output_identity,
    )


def _production_contract(dataset_dir: Path) -> FullPoolExperimentContract:
    return FullPoolExperimentContract(
        schema_version=FULL_POOL_CONTRACT_SCHEMA,
        profile="production",
        validation_token=None,
        dataset_dir=dataset_dir,
        dataset_identity=FULL_POOL_PRODUCTION_DATASET_IDENTITY,
        eligible_user_set_identity=FULL_POOL_PRODUCTION_USER_SET_IDENTITY,
        eligible_user_ids_sha256=FULL_POOL_PRODUCTION_USER_IDS_SHA256,
        eligible_user_count=FULL_POOL_PRODUCTION_USER_COUNT,
        message_ids=("message_1", "message_2", "message_3"),
        message_snapshot_sha256=FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256,
        horizon=FULL_POOL_PRODUCTION_HORIZON,
        per_message_capacity=FULL_POOL_PRODUCTION_CAPACITY,
        seed_top_k_per_proxy=10,
        primary_only=True,
        expected_eligible_pairs=FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
        expected_exposures=FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
        expected_primary_terminals=FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
        expected_committed_batches=FULL_POOL_PRODUCTION_HORIZON,
        expected_candidate_ranking_rows=FULL_POOL_PRODUCTION_CANDIDATE_ROWS,
        expected_final_batch_pairs_per_message=FULL_POOL_PRODUCTION_FINAL_BATCH_PAIRS_PER_MESSAGE,
        output_identity="jinjiang-concurrent-full-pool-formal-v1-gpt-5.6-sol-20260814T120000Z",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_full_pool_validation_closes_complete_primary_only_source_from_batch_spool(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-slice"
    output_dir = tmp_path / "first" / output_identity
    adapter = _DeterministicPrimaryAdapter()

    result = FullPoolFormalExperiment().run(_contract(dataset_dir, output_identity=output_identity), adapter, output_dir)

    assert result.status is FullPoolRunStatus.COMPLETE
    assert result.source_root == output_dir
    assert result.logical_adapter_decisions == 21
    assert result.provider_calls == 0
    assert result.live_api_triggered is False
    assert result.production_deploy_eligible is False
    assert len(adapter.calls) == 21

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    aggregates = json.loads((output_dir / "aggregates.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((output_dir / "diagnostics.json").read_text(encoding="utf-8"))
    candidates = _read_jsonl(output_dir / "candidate_rows.jsonl")
    pairs = _read_jsonl(output_dir / "pair_rows.jsonl")
    terminals = _read_jsonl(output_dir / "terminal_rows.jsonl")

    assert manifest["production_deploy_eligible"] is False
    assert manifest["provider_calls"] == 0
    assert manifest["live_api_triggered"] is False
    assert aggregates["counts"] == {
        "candidate_ranking_rows": 36,
        "committed_batches": 3,
        "distinct_users": 7,
        "eligible_pairs": 21,
        "exposures": 21,
        "primary_terminals": 21,
        "provider_failed_terminals": 0,
        "below_delivery_capacity_pairs": 0,
    }
    assert len(candidates) == 36
    assert len(pairs) == len(terminals) == 21
    assert len({(row["user_id"], row["message_id"]) for row in pairs}) == 21
    assert {row["decision_variant"] for row in terminals} == {"primary"}
    assert diagnostics["coverage"]["per_user_message_count_distribution"] == {"3": 7}
    assert [row["selected_pairs_per_message"] for row in diagnostics["batches"]] == [
        {"message_1": 3, "message_2": 3, "message_3": 3},
        {"message_1": 3, "message_2": 3, "message_3": 3},
        {"message_1": 1, "message_2": 1, "message_3": 1},
    ]
    assert diagnostics["batches"][0]["frozen_campaign_engaged_user_ids"] == []
    assert diagnostics["batches"][0]["committed_primary_positive_user_ids"] == ["u1"]
    assert diagnostics["batches"][1]["frozen_campaign_engaged_user_ids"] == ["u1"]
    assert diagnostics["runtime_resident_row_high_water"] == 48
    assert diagnostics["runtime_resident_rows_after_commit"] == 0
    assert len(list((output_dir / "batches").glob("batch-*.json"))) == 3

    artifact_paths = {entry["relative_path"] for entry in manifest["artifacts"]}
    assert artifact_paths == {
        "aggregates.json",
        "batches/batch-000000.json",
        "batches/batch-000001.json",
        "batches/batch-000002.json",
        "candidate_rows.jsonl",
        "contract.json",
        "diagnostics.json",
        "pair_rows.jsonl",
        "schema.json",
        "terminal_rows.jsonl",
    }
    for entry in manifest["artifacts"]:
        artifact = output_dir / entry["relative_path"]
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == entry["sha256"]
    assert hashlib.sha256((output_dir / "manifest.json").read_bytes()).hexdigest() == result.manifest_sha256
    assert (output_dir.parent / f".{output_identity}.operational").is_dir()


def test_full_pool_validation_uses_shared_seeds_and_independent_message_rankings_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-repeat"

    def reject_run_wide_materialization(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("Full-Pool source closure must stream committed batch chunks")

    monkeypatch.setattr(full_pool_module._ConcurrentRuntimeBatchSpool, "materialize", reject_run_wide_materialization)
    first = tmp_path / "first" / output_identity
    second = tmp_path / "second" / output_identity
    first_result = FullPoolFormalExperiment().run(
        _contract(dataset_dir, output_identity=output_identity),
        _DeterministicPrimaryAdapter(),
        first,
    )
    second_result = FullPoolFormalExperiment().run(
        _contract(dataset_dir, output_identity=output_identity),
        _DeterministicPrimaryAdapter(),
        second,
    )

    assert first_result.manifest_sha256 == second_result.manifest_sha256
    assert first_result.source_identity == second_result.source_identity
    assert _file_bytes(first) == _file_bytes(second)
    batch_zero = json.loads((first / "batches" / "batch-000000.json").read_text(encoding="utf-8"))
    rows = batch_zero["rows"]["pair_rows"]
    selected_by_message = {
        message_id: [row["user_id"] for row in rows if row["message_id"] == message_id]
        for message_id in ("message_1", "message_2", "message_3")
    }
    seeds_by_message = {
        message_id: {
            row["user_id"]
            for row in rows
            if row["message_id"] == message_id and row["selection_reason"] == "seed_union"
        }
        for message_id in ("message_1", "message_2", "message_3")
    }
    assert seeds_by_message == {"message_1": {"u1", "u2"}, "message_2": {"u1", "u2"}, "message_3": {"u1", "u2"}}
    assert selected_by_message["message_1"] != selected_by_message["message_3"]


def test_full_pool_feedback_excludes_ignore_and_provider_failed_terminals(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-failures"
    output_dir = tmp_path / output_identity

    FullPoolFormalExperiment().run(
        _contract(dataset_dir, output_identity=output_identity),
        _ProviderFailurePrimaryAdapter(),
        output_dir,
    )

    aggregates = json.loads((output_dir / "aggregates.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((output_dir / "diagnostics.json").read_text(encoding="utf-8"))
    terminals = _read_jsonl(output_dir / "terminal_rows.jsonl")
    assert aggregates["counts"]["provider_failed_terminals"] == 3
    assert sum(row["terminal_status"] == "provider_failed" for row in terminals) == 3
    assert diagnostics["batches"][0]["committed_primary_positive_user_ids"] == ["u1"]
    assert diagnostics["batches"][1]["frozen_campaign_engaged_user_ids"] == ["u1"]
    assert "u2" not in diagnostics["batches"][1]["frozen_campaign_engaged_user_ids"]
    assert diagnostics["feedback"]["ignore_propagates"] is False
    assert diagnostics["feedback"]["provider_failed_propagates"] is False


def test_full_pool_contract_and_output_facts_fail_before_first_adapter_call(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    adapter = _DeterministicPrimaryAdapter()
    contract = _contract(dataset_dir, output_identity="full-pool-validation-v1-preflight")
    crossed = contract.model_copy(update={"expected_exposures": 20})

    with pytest.raises(FullPoolExperimentError) as crossed_error:
        FullPoolFormalExperiment().run(crossed, adapter, tmp_path / contract.output_identity)
    assert crossed_error.value.code is FullPoolExperimentErrorCode.INVALID_CONTRACT
    assert adapter.calls == []

    with pytest.raises(FullPoolExperimentError) as output_error:
        FullPoolFormalExperiment().run(contract, adapter, tmp_path / "crossed-output")
    assert output_error.value.code is FullPoolExperimentErrorCode.PATH_VIOLATION
    assert adapter.calls == []

    invalid_payload = contract.model_dump(mode="python")
    invalid_payload["unexpected_fact"] = True
    with pytest.raises(ValidationError, match="unexpected_fact"):
        FullPoolExperimentContract.model_validate(invalid_payload)
    assert adapter.calls == []


def test_production_contract_is_static_and_not_executable_as_validation(tmp_path: Path) -> None:
    adapter = _DeterministicPrimaryAdapter()
    contract = _production_contract(tmp_path / "explicit-latent-v1")

    with pytest.raises(FullPoolExperimentError) as error:
        FullPoolFormalExperiment().run(contract, adapter, tmp_path / contract.output_identity)

    assert error.value.code is FullPoolExperimentErrorCode.UNSUPPORTED_PROFILE
    assert adapter.calls == []
    validation_payload = _contract(
        _fixture_dataset(tmp_path / "fixture"),
        output_identity="full-pool-validation-v1-not-production",
    ).model_dump(mode="python")
    validation_payload["profile"] = "production"
    with pytest.raises(ValidationError, match="production contract"):
        FullPoolExperimentContract.model_validate(validation_payload)

    validation_payload["profile"] = "deterministic_validation"
    validation_payload["output_identity"] = contract.output_identity
    with pytest.raises(ValidationError, match="Validation output_identity"):
        FullPoolExperimentContract.model_validate(validation_payload)


def test_validation_rejects_external_request_and_never_creates_final_source(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-external"
    output_dir = tmp_path / output_identity
    adapter = _ExternalRequestPrimaryAdapter()

    with pytest.raises(FullPoolExperimentError) as error:
        FullPoolFormalExperiment().run(_contract(dataset_dir, output_identity=output_identity), adapter, output_dir)

    assert error.value.code is FullPoolExperimentErrorCode.RUNTIME_FAILED
    assert adapter.external_request_invocations == 1
    assert not output_dir.exists()


def test_source_closure_failure_cleans_staging_and_keeps_final_destination_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-atomic"
    output_dir = tmp_path / output_identity

    def fail_validation(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValueError("forced persisted closure failure")

    monkeypatch.setattr(full_pool_module, "_validate_staged_source", fail_validation)
    with pytest.raises(FullPoolExperimentError) as error:
        FullPoolFormalExperiment().run(
            _contract(dataset_dir, output_identity=output_identity),
            _DeterministicPrimaryAdapter(),
            output_dir,
        )

    assert error.value.code is FullPoolExperimentErrorCode.SOURCE_CLOSURE_FAILED
    assert not output_dir.exists()
    assert not list(tmp_path.glob(f".{output_identity}.*.staging"))
    assert (tmp_path / f".{output_identity}.operational").is_dir()


def test_full_pool_interface_remains_package_internal() -> None:
    assert not hasattr(llm_abm_sim, "FullPoolFormalExperiment")
    assert not hasattr(llm_abm_sim, "FullPoolExperimentContract")
    assert not hasattr(full_pool_module, "FullPoolPlanner")
    assert not hasattr(full_pool_module, "FullPoolSourceWriter")
