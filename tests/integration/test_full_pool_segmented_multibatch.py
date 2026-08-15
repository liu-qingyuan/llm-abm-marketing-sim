from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim.concurrent_execution_journal import ConcurrentExecutionJournal
from llm_abm_sim.concurrent_message_experiment import (
    ConcurrentMessageExperimentConfig,
    _PrimaryOnlyConcurrentRuntimeConsumer,
)
from llm_abm_sim.decision import EngageDecision, LLMDecisionAdapter
from llm_abm_sim.final_research import TARGET_VIDEO_ID
from llm_abm_sim.full_pool_segmented_continuation import (
    SEGMENTED_CONCURRENCY_QUALIFICATION_SCHEMA,
    SEGMENTED_OPERATOR_ARTIFACT_ENVELOPE_SCHEMA,
    FullPoolSegmentedContinuation,
    SegmentedContinuationStatus,
    SegmentedQualificationArtifactRef,
    SegmentedQualificationWave,
    _reserve_dynamic_wave,
)
from llm_abm_sim.prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile

MODEL = "offline-segmented-multibatch-v1"


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _dataset(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    _write_csv(
        root / "videos.csv",
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
                "creator_user_id": "target",
                "like_count": 0,
                "comment_count": 0,
                "share_count": 0,
                "collect_count": 0,
            },
            {
                "video_id": "history",
                "source_challenge_name": "锦江酒店",
                "source_challenge_rank": 3,
                "video_url": "https://example.test/history",
                "caption": "history",
                "hashtags": "[]",
                "creator_user_id": "history",
                "like_count": 0,
                "comment_count": 0,
                "share_count": 0,
                "collect_count": 0,
            },
        ],
    )
    _write_csv(
        root / "all_comments.csv",
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
                "comment_id": f"c{number}",
                "video_id": "history",
                "parent_comment_id": "0",
                "commenter_user_id": f"u{number}",
                "mentioned_user_ids": json.dumps(["u1"] if number > 1 else ["u2"]),
                "like_count": 20 - number,
                "comment_level": "comment",
            }
            for number in range(1, 8)
        ],
    )
    latent = [
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
        root / "users.csv",
        [
            "user_id",
            "nickname",
            "bio",
            "signature",
            "follower_count",
            "following_count",
            "video_count",
            "global_influence_score",
            *latent,
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
                "latent_attribute_spec_id": "fixture-v1",
                "latent_attribute_method": "fixture",
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
            for number in range(1, 8)
        ],
    )
    return root


class _PrefixAdapter(LLMDecisionAdapter):
    prompt_version = CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    external_request_invocations = 0
    safe_metadata = {
        "adapter": "offline_segmented_multibatch",
        "provider": "deterministic",
        "model": MODEL,
        "prompt_version": CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        "timeout_seconds": 30.0,
        "max_retries": 2,
    }

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.request_invocations = 0

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        del peer_context, platform_context
        self.request_invocations += 1
        pair_id = f"{profile.user_id}:{post.post_id}:{time_step}"
        self.calls.append(pair_id)
        positive = time_step == 1
        return EngageDecision(
            engage=positive,
            probability=0.9 if positive else 0.1,
            confidence=0.9,
            action="like" if positive else "ignore",
            reason="offline prefix",
            decision_source="offline_segmented_multibatch",
            provider_metadata={"model": MODEL},
        )


class _LaneAdapter(_PrefixAdapter):
    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        decision = super().decide(post, profile, peer_context, platform_context, time_step)
        if time_step == 1 and profile.user_id == "u3":
            return decision.model_copy(
                update={"engage": True, "probability": 0.9, "action": "share"}
            )
        return decision


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_attempt_prefix(workspace: Path) -> None:
    replay = ConcurrentExecutionJournal.open_existing(workspace).replay()
    terminals = [
        record["payload"]["variant_evidence"]
        for record in replay["records"]
        if record.get("event_type") == "variant_terminal"
    ]
    execution_hash = "a" * 64
    identity = {
        "schema_version": "full-pool-formal-operational-identity-v1",
        "output_identity": "multibatch-static-copy",
        "contract_sha256": "b" * 64,
        "execution_contract_sha256": execution_hash,
        "authorization_artifact_sha256": "c" * 64,
        "qualification_artifact_sha256": "d" * 64,
        "operational_root": "/static/v1",
        "source_root": "/static/source",
        "candidate_root": "/static/candidate",
        "production_deploy_eligible": False,
    }
    (workspace / "full_pool_execution_identity.json").write_text(_canonical(identity), encoding="utf-8")
    sequence = 0
    previous: str | None = None
    rows: list[dict[str, object]] = []

    def add(event_type: str, payload: dict[str, object]) -> None:
        nonlocal sequence, previous
        sequence += 1
        body = {
            "schema_version": "full-pool-formal-attempt-ledger-v1",
            "sequence": sequence,
            "previous_checksum": previous,
            "execution_contract_sha256": execution_hash,
            "event_type": event_type,
            "payload": payload,
        }
        checksum = hashlib.sha256(_canonical(body).encode()).hexdigest()
        rows.append({**body, "checksum": checksum})
        previous = checksum

    physical = 0
    for evidence in terminals:
        pair_id = str(evidence["pair_id"])
        requests = int(evidence["request_invocations"])
        add(
            "judgment_reserved",
            {
                "pair_id": pair_id,
                "reserved_logical_judgments": len(rows) + 1,
                "reserved_physical_attempts": physical + 3,
                "maximum_physical_attempts": 3,
            },
        )
        for attempt in range(1, requests + 1):
            add(
                "physical_attempt_accounted",
                {"pair_id": pair_id, "attempt_index": attempt, "attempt_outcome": "terminal_succeeded"},
            )
        accounting = {
            key: evidence[key]
            for key in (
                "request_invocations",
                "provider_response_count",
                "successful_decision_count",
                "observed_model_counts",
                "observed_model_missing_response_count",
                "observed_model_malformed_response_count",
                "usage_complete",
                "usage_complete_response_count",
                "usage_missing_response_count",
                "usage_malformed_response_count",
                "input_usage",
                "output_usage",
                "total_usage",
                "cached_input_usage",
            )
        }
        add("judgment_terminal", {"pair_id": pair_id, "terminal_status": "succeeded", "accounting": accounting})
        physical += requests
    (workspace / "full_pool_attempt_ledger.jsonl").write_text(
        "".join(_canonical(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    status = {
        "schema_version": "full-pool-formal-operational-status-v1",
        "lifecycle": "resumable_interruption",
        "execution_contract_sha256": execution_hash,
        "logical_judgments": len(terminals),
        "physical_attempts": physical,
        "reserved_logical_judgments": len(terminals),
        "reserved_physical_attempts": physical,
        "last_pair_id": terminals[-1]["pair_id"],
        "production_deploy_eligible": False,
    }
    (workspace / "full_pool_execution_status.json").write_text(_canonical(status), encoding="utf-8")


def _mid_batch_prefix(
    tmp_path: Path,
    *,
    horizon: int = 3,
    delivery_capacity: int = 3,
    terminal_limit: int = 11,
) -> tuple[Path, Path, list[str]]:
    dataset = _dataset(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset,
        sample_size=7,
        horizon=horizon,
        delivery_capacity=delivery_capacity,
        configuration_profile="validation",
    )
    calls: list[str] = []
    adapter = _PrefixAdapter(calls)
    terminal_count = 0

    def interrupt_after_second_batch_one_terminal(_evidence: Mapping[str, object]) -> None:
        nonlocal terminal_count
        terminal_count += 1
        if terminal_count == terminal_limit:
            raise RuntimeError("static cutoff at the requested terminal boundary")

    output = tmp_path / "old-v1-output"
    consumer = _PrimaryOnlyConcurrentRuntimeConsumer(
        config,
        adapter,
        execution_contract={
            "schema_version": "full-pool-experiment-contract-v1",
            "seed_top_k_per_proxy": 2,
            "logical_judgment_cap": 109_200,
            "physical_attempt_cap": 120_120,
            "worker_count": 1,
            "request_contract": {"max_retries": 2},
        },
        after_logical_judgment=interrupt_after_second_batch_one_terminal,
    )
    with pytest.raises(RuntimeError, match="static cutoff"):
        consumer._run_new_to_spool(output)
    operational = output.parent / f".{output.name}.operational"
    _write_attempt_prefix(operational)
    static_copy = tmp_path / "static-v1-copy"
    shutil.copytree(operational, static_copy)
    return static_copy, dataset, calls


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_multibatch_continuation_finishes_active_batch_plans_batch_two_and_closes_source_v2(
    tmp_path: Path,
) -> None:
    prefix, _dataset_dir, prefix_calls = _mid_batch_prefix(tmp_path)
    prefix_terminal_ids = {
        record["payload"]["pair_id"]
        for record in ConcurrentExecutionJournal.open_existing(prefix).replay()["records"]
        if record.get("event_type") == "variant_terminal"
    }
    suffix_calls: list[str] = []

    result = FullPoolSegmentedContinuation().run(
        prefix,
        tmp_path / "continuation",
        continuation_id="three-batch-mid-batch-one-v1",
        adapter_factory=lambda _lane_id: _LaneAdapter(suffix_calls),
    )

    assert result.status is SegmentedContinuationStatus.COMPLETE
    assert result.logical_count == 21
    assert result.physical_attempt_count == 21
    assert result.durable_prefix_terminal_count == 11
    assert result.concurrent_suffix_terminal_count == 10
    assert prefix_terminal_ids.isdisjoint(suffix_calls)
    assert len(suffix_calls) == 10
    assert any(pair_id.endswith(":2") for pair_id in suffix_calls)
    assert result.source_root is not None
    source = result.source_root
    candidate_rows = _read_jsonl(source / "candidate_rows.jsonl")
    pair_rows = _read_jsonl(source / "pair_rows.jsonl")
    terminal_rows = _read_jsonl(source / "terminal_rows.jsonl")
    steps = _read_jsonl(source / "steps.jsonl")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    assert len(pair_rows) == len(terminal_rows) == 21
    assert len({row["pair_id"] for row in pair_rows}) == 21
    assert len(candidate_rows) == 36
    assert [row["time_step"] for row in steps] == [0, 1, 2]
    assert set(steps[2]["frozen_campaign_engaged_user_ids"]) == set(
        steps[0]["committed_primary_positive_user_ids"]
    ) | set(steps[1]["committed_primary_positive_user_ids"])
    assert len(steps[1]["committed_primary_positive_user_ids"]) >= 3
    assert steps[2]["frozen_campaign_engaged_user_ids"] == steps[1][
        "committed_primary_positive_user_ids"
    ]
    assert manifest["counts"] == {
        "candidate_rows": 36,
        "pair_rows": 21,
        "terminal_rows": 21,
        "steps": 3,
    }
    assert manifest["logical_count"] == 21
    assert manifest["physical_attempt_count"] == 21
    assert manifest["accounting"]["invocations"] == 21
    assert manifest["accounting"]["migration_unknown_physical_charge"] == 0
    assert manifest["cutoff_manifest_sha256"] == result.manifest_sha256
    assert manifest["production_deploy_eligible"] is False
    assert len(prefix_calls) == 11

    factory_called = False

    def tripwire(_lane_id: int) -> LLMDecisionAdapter:
        nonlocal factory_called
        factory_called = True
        raise AssertionError("closed source-v2 must replay without Adapter creation")

    replay = FullPoolSegmentedContinuation().run(
        prefix,
        tmp_path / "continuation",
        continuation_id="three-batch-mid-batch-one-v1",
        adapter_factory=tripwire,
    )
    assert replay == result
    assert factory_called is False


def test_complete_source_v2_recovers_missing_status_without_calls_and_rejects_tamper(
    tmp_path: Path,
) -> None:
    prefix, _dataset_dir, _prefix_calls = _mid_batch_prefix(tmp_path)
    workspace = tmp_path / "recoverable-continuation"
    first = FullPoolSegmentedContinuation().run(
        prefix,
        workspace,
        continuation_id="recoverable-source-v2-v1",
        adapter_factory=lambda _lane_id: _LaneAdapter([]),
    )
    status_path = workspace / "segmented_continuation_status.json"
    status_path.unlink()
    factory_called = False

    def tripwire(_lane_id: int) -> LLMDecisionAdapter:
        nonlocal factory_called
        factory_called = True
        raise AssertionError("source-v2 recovery must not create Adapter lanes")

    recovered = FullPoolSegmentedContinuation().run(
        prefix,
        workspace,
        continuation_id="recoverable-source-v2-v1",
        adapter_factory=tripwire,
    )
    assert recovered == first
    assert status_path.is_file()
    assert factory_called is False

    status_path.unlink()
    terminal_path = workspace / "source-v2" / "terminal_rows.jsonl"
    terminal_path.write_bytes(terminal_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="source-v2 artifact hash mismatch"):
        FullPoolSegmentedContinuation().run(
            prefix,
            workspace,
            continuation_id="recoverable-source-v2-v1",
            adapter_factory=tripwire,
        )
    assert factory_called is False


def test_source_v2_embeds_and_revalidates_exact_first_wave_qualification(tmp_path: Path) -> None:
    prefix, _dataset_dir, _prefix_calls = _mid_batch_prefix(
        tmp_path,
        horizon=2,
        delivery_capacity=4,
        terminal_limit=2,
    )
    external_qualification = tmp_path / "qualification.json"

    def qualify(wave: SegmentedQualificationWave) -> SegmentedQualificationArtifactRef:
        payload = {
            "schema_version": SEGMENTED_CONCURRENCY_QUALIFICATION_SCHEMA,
            "continuation_authorization_sha256": "a" * 64,
            "mode": "first-wave-formal-remaining-pairs",
            "status": "qualified",
            "pair_ids": list(wave.pair_ids),
            "lane_count": 10,
            "elapsed_seconds": 2.0,
            "actual_request_rate_per_second": 5.0,
            "physical_attempt_count": 10,
            "provider_response_count": 10,
            "successful_decision_count": 10,
            "error_count": 0,
            "terminal_status_counts": {"succeeded": 10},
            "observed_model_counts": {"gpt-5.6-sol": 10},
            "usage_complete_response_count": 10,
            "usage_missing_response_count": 0,
            "usage_malformed_response_count": 0,
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "cached_input_tokens": 0,
            "formal_remaining_pairs_consumed": 10,
            "provider_concurrency_reduction": False,
            "production_deploy_eligible": False,
        }
        payload_sha256 = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        envelope = {
            "schema_version": SEGMENTED_OPERATOR_ARTIFACT_ENVELOPE_SCHEMA,
            "payload": payload,
            "payload_sha256": payload_sha256,
        }
        external_qualification.write_text(
            json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return SegmentedQualificationArtifactRef(
            path=external_qualification,
            sha256=hashlib.sha256(external_qualification.read_bytes()).hexdigest(),
        )

    result = FullPoolSegmentedContinuation().run(
        prefix,
        tmp_path / "qualified-continuation",
        continuation_id="qualified-source-v2",
        adapter_factory=lambda _lane_id: _LaneAdapter([]),
        first_wave_observer=qualify,
    )
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None
    manifest = json.loads((result.source_root / "manifest.json").read_text(encoding="utf-8"))
    qualification_hash = hashlib.sha256(external_qualification.read_bytes()).hexdigest()
    assert manifest["concurrency_qualification_artifact_sha256"] == qualification_hash
    copied = result.source_root / "concurrency_qualification.json"
    assert copied.read_bytes() == external_qualification.read_bytes()
    status_path = result.workspace_root / "segmented_continuation_status.json"
    status_path.unlink()
    recovered = FullPoolSegmentedContinuation().run(
        prefix,
        result.workspace_root,
        continuation_id="qualified-source-v2",
        adapter_factory=lambda _lane_id: (_ for _ in ()).throw(
            AssertionError("qualified source recovery must not create Adapter lanes")
        ),
    )
    assert recovered == result
    status_path.unlink()
    copied.write_bytes(copied.read_bytes() + b" ")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        FullPoolSegmentedContinuation().run(
            prefix,
            result.workspace_root,
            continuation_id="qualified-source-v2",
            adapter_factory=lambda _lane_id: (_ for _ in ()).throw(
                AssertionError("qualification tamper must fail before Adapter creation")
            ),
        )


def test_dynamic_wave_reservation_shrinks_near_physical_cap_and_stops_without_dispatch() -> None:
    reservation = _reserve_dynamic_wave(
        remaining_pair_count=10,
        physical_attempts=120_108,
        maximum_attempts_per_dispatch=3,
    )
    assert reservation.wave_size == 4
    assert reservation.reserved_physical_attempts == 12

    stopped = _reserve_dynamic_wave(
        remaining_pair_count=10,
        physical_attempts=120_118,
        maximum_attempts_per_dispatch=3,
    )
    assert stopped.wave_size == 0
    assert stopped.reserved_physical_attempts == 0
