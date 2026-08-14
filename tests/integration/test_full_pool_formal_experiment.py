from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import ValidationError

import llm_abm_sim
import llm_abm_sim.full_pool_formal_experiment as full_pool_module
from llm_abm_sim.concurrent_execution_journal import (
    CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON,
    CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR,
    ConcurrentExecutionJournal,
)
from llm_abm_sim.decision import (
    DecisionInput,
    EngageDecision,
    LLMDecisionAdapter,
    ProviderDecisionError,
    ProviderResponseProvenanceUnknown,
)
from llm_abm_sim.final_research import TARGET_VIDEO_ID
from llm_abm_sim.full_pool_formal_experiment import (
    FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256,
    FULL_POOL_CONTRACT_SCHEMA,
    FULL_POOL_FORMAL_ADAPTER_IDENTITY,
    FULL_POOL_FORMAL_ATTEMPT_RESERVATION_POLICY,
    FULL_POOL_FORMAL_AUTHORIZATION_SCHEMA,
    FULL_POOL_FORMAL_DECISION_STORE_POLICY,
    FULL_POOL_FORMAL_EXECUTION_SCHEMA,
    FULL_POOL_FORMAL_LOGICAL_JUDGMENT_CAP,
    FULL_POOL_FORMAL_OAUTH_ACCOUNT_BINDING,
    FULL_POOL_FORMAL_OBSERVED_EVIDENCE_SCHEMA,
    FULL_POOL_FORMAL_OBSERVED_MODEL_POLICY,
    FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP,
    FULL_POOL_FORMAL_QUALIFICATION_FRESHNESS_POLICY,
    FULL_POOL_FORMAL_QUALIFICATION_SCHEMA,
    FULL_POOL_FORMAL_RECONCILIATION_POLICY,
    FULL_POOL_FORMAL_REQUESTED_MODEL,
    FULL_POOL_FORMAL_TRANSPORT,
    FULL_POOL_FORMAL_VALIDATION_ACCOUNT_BINDING,
    FULL_POOL_FORMAL_VALIDATION_ADAPTER_IDENTITY,
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
    FullPoolFormalAuthorization,
    FullPoolFormalExecutionContract,
    FullPoolFormalExperiment,
    FullPoolFormalQualification,
    FullPoolFormalRequestContract,
    FullPoolRunStatus,
)
from llm_abm_sim.prompt_contracts import (
    APPROVED_EXCLUDED_FIELDS,
    APPROVED_VISIBLE_FIELD_ALLOWLIST,
    CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY,
)
from llm_abm_sim.prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from llm_abm_sim.provider_accounting import ProviderResponseEnvelope
from llm_abm_sim.provider_request_contract import (
    OMITTED_SAMPLING_PARAMETERS,
    STRUCTURED_OUTPUT_SCHEMA_HASH,
)
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter
from llm_abm_sim.providers.pi_subscription import PI_SUBSCRIPTION_ADAPTER_IDENTITY
from llm_abm_sim.schemas import (
    FailClosedAction,
    PeerContext,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    ReasoningEffort,
    UserProfile,
)


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


def _write_contract_artifact(path: Path, payload: dict[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_text(content, encoding="utf-8", newline="\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _formal_execution_contract(
    contract: FullPoolExperimentContract,
    output_dir: Path,
    *,
    evidence_profile: Literal["deterministic_validation_fixture", "formal_live"] = (
        "deterministic_validation_fixture"
    ),
    active_logical_cap: int | None = None,
    active_physical_cap: int | None = None,
) -> FullPoolFormalExecutionContract:
    prompt = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION)
    formal_live = evidence_profile == "formal_live"
    authorization_kind = "formal_live_provider" if formal_live else "deterministic_validation_fixture"
    adapter_identity = (
        FULL_POOL_FORMAL_ADAPTER_IDENTITY if formal_live else FULL_POOL_FORMAL_VALIDATION_ADAPTER_IDENTITY
    )
    account_binding = (
        FULL_POOL_FORMAL_OAUTH_ACCOUNT_BINDING
        if formal_live
        else FULL_POOL_FORMAL_VALIDATION_ACCOUNT_BINDING
    )
    authorization_at = "2026-08-14T10:00:00Z"
    qualification_at = "2026-08-14T11:00:00Z"
    expires_at = "2026-08-14T13:00:00Z"
    artifact_root = output_dir.parent / f".{output_dir.name}.formal-contract"
    authorization_path = artifact_root / "execution_authorization.json"
    qualification_path = artifact_root / "model_qualification.json"
    observed_evidence_path = artifact_root / "observed_model_evidence.json"
    authorization_payload: dict[str, object] = {
        "schema_version": FULL_POOL_FORMAL_AUTHORIZATION_SCHEMA,
        "authorization_kind": authorization_kind,
        "authorization_reference": "artifact://full-pool-explicit-authorization",
        "authorized_at_utc": authorization_at,
        "expires_at_utc": expires_at,
        "account_binding": account_binding,
        "output_identity": contract.output_identity,
        "dataset_identity": contract.dataset_identity,
        "eligible_user_ids_sha256": contract.eligible_user_ids_sha256,
        "message_snapshot_sha256": contract.message_snapshot_sha256,
        "provider": "openai_compatible",
        "transport": FULL_POOL_FORMAL_TRANSPORT,
        "adapter_identity": adapter_identity,
        "requested_model": FULL_POOL_FORMAL_REQUESTED_MODEL,
        "required_observed_model": "gpt-5.6-sol",
        "logical_judgment_cap": FULL_POOL_FORMAL_LOGICAL_JUDGMENT_CAP,
        "physical_attempt_cap": FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP,
        "worker_count": 1,
        "subscription_billed_cost_usd": 0.0,
        "external_requests_allowed": formal_live,
        "production_deploy_eligible": False,
    }
    authorization_hash = _write_contract_artifact(authorization_path, authorization_payload)
    observed_evidence_payload: dict[str, object] = {
        "schema_version": FULL_POOL_FORMAL_OBSERVED_EVIDENCE_SCHEMA,
        "evidence_kind": "provider_observed" if formal_live else "deterministic_validation_fixture",
        "output_identity": contract.output_identity,
        "provider": "openai_compatible",
        "transport": FULL_POOL_FORMAL_TRANSPORT,
        "adapter_identity": adapter_identity,
        "requested_model": FULL_POOL_FORMAL_REQUESTED_MODEL,
        "observed_model": "gpt-5.6-sol",
        "account_binding": account_binding,
        "qualified_at_utc": qualification_at,
        "usage_complete": True,
        "raw_provider_payload_persisted": False,
    }
    observed_evidence_hash = _write_contract_artifact(observed_evidence_path, observed_evidence_payload)
    qualification_payload: dict[str, object] = {
        "schema_version": FULL_POOL_FORMAL_QUALIFICATION_SCHEMA,
        "qualification_kind": "provider_observed" if formal_live else "deterministic_validation_fixture",
        "artifact_reference": "artifact://full-pool-fresh-model-qualification",
        "authorization_artifact_sha256": authorization_hash,
        "qualified_at_utc": qualification_at,
        "expires_at_utc": expires_at,
        "account_binding": account_binding,
        "observed_response_sha256": observed_evidence_hash,
        "output_identity": contract.output_identity,
        "provider": "openai_compatible",
        "transport": FULL_POOL_FORMAL_TRANSPORT,
        "requested_model": FULL_POOL_FORMAL_REQUESTED_MODEL,
        "required_observed_model": "gpt-5.6-sol",
        "freshness_policy": FULL_POOL_FORMAL_QUALIFICATION_FRESHNESS_POLICY,
        "status": "qualified",
    }
    qualification_hash = _write_contract_artifact(qualification_path, qualification_payload)
    return FullPoolFormalExecutionContract(
        schema_version=FULL_POOL_FORMAL_EXECUTION_SCHEMA,
        evidence_profile=evidence_profile,
        provider="openai_compatible",
        transport=FULL_POOL_FORMAL_TRANSPORT,
        adapter_identity=adapter_identity,
        requested_model=FULL_POOL_FORMAL_REQUESTED_MODEL,
        required_observed_model="gpt-5.6-sol",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        prompt_canonical_hash=prompt.canonical_hash,
        visible_field_allowlist=APPROVED_VISIBLE_FIELD_ALLOWLIST,
        excluded_fields=APPROVED_EXCLUDED_FIELDS,
        request_contract=FullPoolFormalRequestContract(
            schema_version="provider-request-contract-v1",
            requested_model=FULL_POOL_FORMAL_REQUESTED_MODEL,
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            prompt_canonical_hash=prompt.canonical_hash,
            wire_api="responses",
            reasoning_effort="low",
            output_token_ceiling=256,
            timeout_seconds=30.0,
            max_retries=2,
            retry_backoff_seconds=1.0,
            structured_output_schema_version="engage-decision-output-v1",
            structured_output_schema_hash=STRUCTURED_OUTPUT_SCHEMA_HASH,
            omitted_parameters=OMITTED_SAMPLING_PARAMETERS,
        ),
        decision_store_policy=FULL_POOL_FORMAL_DECISION_STORE_POLICY,
        attempt_reservation_policy=FULL_POOL_FORMAL_ATTEMPT_RESERVATION_POLICY,
        observed_model_policy=FULL_POOL_FORMAL_OBSERVED_MODEL_POLICY,
        reconciliation_policy=FULL_POOL_FORMAL_RECONCILIATION_POLICY,
        worker_count=1,
        logical_judgment_cap=FULL_POOL_FORMAL_LOGICAL_JUDGMENT_CAP,
        physical_attempt_cap=FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP,
        active_logical_judgment_cap=active_logical_cap or contract.expected_primary_terminals,
        active_physical_attempt_cap=active_physical_cap or contract.expected_primary_terminals + 2,
        subscription_billed_cost_usd=0.0,
        operational_root=output_dir.parent / f".{output_dir.name}.operational",
        source_root=output_dir,
        candidate_root=output_dir.with_name(f"{output_dir.name}-report-candidate"),
        authorization=FullPoolFormalAuthorization.model_validate(
            {
                "artifact_path": authorization_path,
                "artifact_sha256": authorization_hash,
                **authorization_payload,
            }
        ),
        qualification=FullPoolFormalQualification.model_validate(
            {
                "artifact_path": qualification_path,
                "artifact_sha256": qualification_hash,
                "observed_response_artifact_path": observed_evidence_path,
                **qualification_payload,
            }
        ),
    )


class _FormalValidationProviderClient:
    safe_metadata = {
        "provider_transport": FULL_POOL_FORMAL_TRANSPORT,
        "adapter_identity": FULL_POOL_FORMAL_VALIDATION_ADAPTER_IDENTITY,
        "authentication": "deterministic_validation_fixture",
    }

    def __init__(self, responses: list[ProviderResponseEnvelope | Exception] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.responses = list(responses or [])

    def create_response(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        reasoning_effort: str | None = None,
        output_token_ceiling: int | None = None,
    ) -> ProviderResponseEnvelope:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "output_token_ceiling": output_token_ceiling,
            }
        )
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return ProviderResponseEnvelope(
            decision_text=json.dumps(
                {
                    "engage": False,
                    "probability": 0.1,
                    "reason": "deterministic formal-shaped validation",
                    "confidence": 0.9,
                    "action": "ignore",
                }
            ),
            observed_model="gpt-5.6-sol",
            observed_model_status="reported",
            usage_status="complete",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            cached_input_tokens=0,
        )


def _formal_validation_adapter(client: Any) -> OpenAICompatibleDecisionAdapter:
    return OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="openai_compatible",
            model=FULL_POOL_FORMAL_REQUESTED_MODEL,
            wire_api="responses",
            require_live_env=True,
            timeout_seconds=30.0,
            max_retries=2,
            retry_backoff_seconds=1.0,
            fail_closed_action=FailClosedAction.RAISE,
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            reasoning_effort=ReasoningEffort.LOW,
            max_output_tokens=256,
        ),
        client=client,
        sleep=lambda _: None,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_formal_execution_preflight_rejects_crossed_adapter_before_calls(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-formal-preflight"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir)
    contract = base_contract.model_copy(update={"formal_execution": execution})

    class CrossedClient:
        safe_metadata = {
            "provider_transport": FULL_POOL_FORMAL_TRANSPORT,
            "adapter_identity": "crossed-validation-adapter",
        }

        def create_response(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("preflight must fail before the first Provider call")

    adapter = _formal_validation_adapter(CrossedClient())

    with pytest.raises(FullPoolExperimentError) as captured:
        FullPoolFormalExperiment().run(contract, adapter, output_dir)

    assert captured.value.code is FullPoolExperimentErrorCode.INVALID_ADAPTER
    assert adapter.request_invocations == 0
    assert adapter.external_request_invocations == 0
    assert not output_dir.exists()


def test_formal_execution_rejects_tampered_authorization_artifact_before_calls(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-artifact-tamper"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    execution.authorization.artifact_path.write_bytes(
        execution.authorization.artifact_path.read_bytes() + b" "
    )
    client = _FormalValidationProviderClient()
    adapter = _formal_validation_adapter(client)

    with pytest.raises(FullPoolExperimentError) as captured:
        FullPoolFormalExperiment().run(contract, adapter, output_dir)

    assert captured.value.code is FullPoolExperimentErrorCode.INVALID_ADAPTER
    assert client.calls == []
    assert adapter.request_invocations == 0
    assert not output_dir.exists()
    assert not execution.operational_root.exists()


def test_formal_live_execution_rejects_stale_model_qualification_window(tmp_path: Path) -> None:
    base_contract = _production_contract(tmp_path / "stale-qualification-dataset")
    output_dir = tmp_path / base_contract.output_identity
    execution = _formal_execution_contract(
        base_contract,
        output_dir,
        evidence_profile="formal_live",
        active_logical_cap=FULL_POOL_FORMAL_LOGICAL_JUDGMENT_CAP,
        active_physical_cap=FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP,
    )
    payload = execution.model_dump(mode="python")
    qualification = dict(payload["qualification"])
    qualification["qualified_at_utc"] = "2026-08-14T10:30:00Z"
    qualification["expires_at_utc"] = "2026-08-14T11:30:00Z"
    payload["qualification"] = qualification

    with pytest.raises(ValidationError, match="qualification freshness"):
        FullPoolFormalExecutionContract.model_validate(payload)


def test_production_formal_contract_requires_pi_subscription_transport_before_dataset_or_calls(
    tmp_path: Path,
) -> None:
    base_contract = _production_contract(tmp_path / "missing-explicit-latent-v1")
    output_dir = tmp_path / base_contract.output_identity
    execution = _formal_execution_contract(
        base_contract,
        output_dir,
        evidence_profile="formal_live",
        active_logical_cap=FULL_POOL_FORMAL_LOGICAL_JUDGMENT_CAP,
        active_physical_cap=FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP,
    )
    contract = base_contract.model_copy(update={"formal_execution": execution})
    base_contract.dataset_dir.mkdir(parents=True)
    client = _FormalValidationProviderClient()
    adapter = _formal_validation_adapter(client)

    with pytest.raises(FullPoolExperimentError) as captured:
        FullPoolFormalExperiment().run(contract, adapter, output_dir)

    assert FULL_POOL_FORMAL_ADAPTER_IDENTITY == PI_SUBSCRIPTION_ADAPTER_IDENTITY
    assert captured.value.code is FullPoolExperimentErrorCode.INVALID_ADAPTER
    assert client.calls == []
    assert adapter.request_invocations == 0
    assert not output_dir.exists()


def test_formal_shaped_validation_persists_attempts_and_closes_non_production_source(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-formal-lifecycle"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    client = _FormalValidationProviderClient()
    adapter = _formal_validation_adapter(client)

    result = FullPoolFormalExperiment().run(contract, adapter, output_dir)

    assert result.status is FullPoolRunStatus.COMPLETE
    assert result.logical_adapter_decisions == 21
    assert result.physical_provider_attempts == 21
    assert result.provider_calls == 0
    assert result.live_api_triggered is False
    assert result.production_deploy_eligible is False
    assert len(client.calls) == 21
    assert all(
        call["model"] == "gpt-5.6-sol"
        and call["reasoning_effort"] == "low"
        and call["output_token_ceiling"] == 256
        for call in client.calls
    )

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    aggregates = json.loads((output_dir / "aggregates.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "full-pool-formal-manifest-v1"
    assert manifest["source_schema_version"] == "full-pool-formal-source-v1"
    assert manifest["evidence_profile"] == "deterministic_validation_fixture"
    assert manifest["physical_provider_attempts"] == 21
    assert manifest["provider_calls"] == 0
    assert manifest["live_api_triggered"] is False
    assert manifest["production_deploy_eligible"] is False
    assert (output_dir / "execution_authorization.json").read_bytes() == execution.authorization.artifact_path.read_bytes()
    assert (output_dir / "model_qualification.json").read_bytes() == execution.qualification.artifact_path.read_bytes()
    assert (output_dir / "observed_model_evidence.json").read_bytes() == (
        execution.qualification.observed_response_artifact_path.read_bytes()
    )
    assert aggregates["provider_accounting"]["logical_judgments"] == 21
    assert aggregates["provider_accounting"]["physical_attempts"] == 21
    assert aggregates["provider_accounting"]["observed_model_counts"] == {"gpt-5.6-sol": 21}
    assert aggregates["provider_accounting"]["usage_complete_response_count"] == 21

    operational = output_dir.parent / f".{output_identity}.operational"
    identity = json.loads((operational / "full_pool_execution_identity.json").read_text(encoding="utf-8"))
    status = json.loads((operational / "full_pool_execution_status.json").read_text(encoding="utf-8"))
    ledger = _read_jsonl(operational / "full_pool_attempt_ledger.jsonl")
    assert identity["execution_contract_sha256"] == hashlib.sha256(
        json.dumps(execution.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert status["lifecycle"] == "ready_to_close"
    assert status["logical_judgments"] == 21
    assert status["physical_attempts"] == 21
    assert sum(row["event_type"] == "judgment_reserved" for row in ledger) == 21
    assert sum(row["event_type"] == "physical_attempt_accounted" for row in ledger) == 21
    assert sum(row["event_type"] == "judgment_terminal" for row in ledger) == 21


def test_formal_attempt_cap_stops_before_dispatch_and_returns_resumable(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-cap-stop"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir, active_physical_cap=2)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    client = _FormalValidationProviderClient()
    adapter = _formal_validation_adapter(client)

    result = FullPoolFormalExperiment().run(contract, adapter, output_dir)

    assert result.status is FullPoolRunStatus.RESUMABLE
    assert result.workspace_root == output_dir.parent / f".{output_identity}.operational"
    assert result.source_root is None
    assert result.source_identity is None
    assert result.manifest_sha256 is None
    assert result.logical_adapter_decisions == 0
    assert result.physical_provider_attempts == 0
    assert result.provider_calls == 0
    assert client.calls == []
    assert not output_dir.exists()
    status = json.loads(
        (result.workspace_root / "full_pool_execution_status.json").read_text(encoding="utf-8")
    )
    assert status["lifecycle"] == "resumable_cap_stop"
    assert status["reserved_logical_judgments"] == 1
    assert status["reserved_physical_attempts"] == 3
    ledger_before = (result.workspace_root / "full_pool_attempt_ledger.jsonl").read_bytes()
    resume_client = _FormalValidationProviderClient()
    resumed = FullPoolFormalExperiment().run(contract, _formal_validation_adapter(resume_client), output_dir)
    assert resumed == result
    assert resume_client.calls == []
    assert (result.workspace_root / "full_pool_attempt_ledger.jsonl").read_bytes() == ledger_before


def test_formal_safe_terminal_interruption_resumes_without_replaying_closed_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-safe-resume"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    first_client = _FormalValidationProviderClient()
    original_after = full_pool_module._FullPoolAttemptGuard.after
    interrupted = False

    def interrupt_after_durable_terminal(self: Any, evidence: Any) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise RuntimeError("injected safe interruption after journal terminal before attempt-ledger close")
        original_after(self, evidence)

    monkeypatch.setattr(full_pool_module._FullPoolAttemptGuard, "after", interrupt_after_durable_terminal)
    partial = FullPoolFormalExperiment().run(contract, _formal_validation_adapter(first_client), output_dir)

    assert partial.status is FullPoolRunStatus.RESUMABLE
    assert partial.logical_adapter_decisions == 0
    assert partial.physical_provider_attempts == 0
    assert len(first_client.calls) == 1
    assert not output_dir.exists()

    monkeypatch.setattr(full_pool_module._FullPoolAttemptGuard, "after", original_after)
    resume_client = _FormalValidationProviderClient()
    complete = FullPoolFormalExperiment().run(contract, _formal_validation_adapter(resume_client), output_dir)

    assert complete.status is FullPoolRunStatus.COMPLETE
    assert complete.logical_adapter_decisions == 21
    assert complete.physical_provider_attempts == 21
    assert len(resume_client.calls) == 20
    ledger = _read_jsonl(execution.operational_root / "full_pool_attempt_ledger.jsonl")
    assert sum(row["event_type"] == "judgment_terminal" for row in ledger) == 21
    assert len(
        {
            row["payload"]["pair_id"]
            for row in ledger
            if row["event_type"] == "judgment_terminal"
        }
    ) == 21


def test_formal_unknown_inflight_requires_reconciliation_and_never_replays(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-reconciliation"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    first_client = _FormalValidationProviderClient(
        [ProviderResponseProvenanceUnknown("request dispatched but response provenance is unknown")]
    )
    first_adapter = _formal_validation_adapter(first_client)

    partial = FullPoolFormalExperiment().run(contract, first_adapter, output_dir)

    assert partial.status is FullPoolRunStatus.RECONCILIATION_REQUIRED
    assert partial.logical_adapter_decisions == 0
    assert partial.physical_provider_attempts == 0
    assert len(first_client.calls) == 1
    assert first_adapter.request_invocations == 1
    assert not output_dir.exists()
    first_ledger = (execution.operational_root / "full_pool_attempt_ledger.jsonl").read_bytes()

    resume_client = _FormalValidationProviderClient()
    blocked = FullPoolFormalExperiment().run(contract, _formal_validation_adapter(resume_client), output_dir)

    assert blocked.status is FullPoolRunStatus.RECONCILIATION_REQUIRED
    assert blocked.logical_adapter_decisions == 0
    assert blocked.physical_provider_attempts == 0
    assert resume_client.calls == []
    assert (execution.operational_root / "full_pool_attempt_ledger.jsonl").read_bytes() == first_ledger
    status = json.loads(
        (execution.operational_root / "full_pool_execution_status.json").read_text(encoding="utf-8")
    )
    assert status["lifecycle"] == "reconciliation_required"
    assert not output_dir.exists()


def test_formal_observed_model_drift_fails_closed_then_requires_reconciliation(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-model-drift"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    drifted = ProviderResponseEnvelope(
        decision_text=json.dumps(
            {
                "engage": False,
                "probability": 0.1,
                "reason": "drifted model",
                "confidence": 0.9,
                "action": "ignore",
            }
        ),
        observed_model="gpt-unqualified-alias",
        observed_model_status="reported",
        usage_status="complete",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        cached_input_tokens=0,
    )
    drift_client = _FormalValidationProviderClient([drifted])

    with pytest.raises(FullPoolExperimentError) as captured:
        FullPoolFormalExperiment().run(contract, _formal_validation_adapter(drift_client), output_dir)

    assert captured.value.code is FullPoolExperimentErrorCode.RUNTIME_FAILED
    assert len(drift_client.calls) == 1
    assert not output_dir.exists()
    resume_client = _FormalValidationProviderClient()
    blocked = FullPoolFormalExperiment().run(contract, _formal_validation_adapter(resume_client), output_dir)
    assert blocked.status is FullPoolRunStatus.RECONCILIATION_REQUIRED
    assert resume_client.calls == []
    assert not output_dir.exists()


def test_formal_retry_and_provider_failed_accounting_remain_explicit(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-retry-accounting"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir, active_physical_cap=30)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    success = ProviderResponseEnvelope(
        decision_text=json.dumps(
            {
                "engage": False,
                "probability": 0.1,
                "reason": "retry validation",
                "confidence": 0.9,
                "action": "ignore",
            }
        ),
        observed_model="gpt-5.6-sol",
        observed_model_status="reported",
        usage_status="complete",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        cached_input_tokens=0,
    )
    responses: list[ProviderResponseEnvelope | Exception] = [
        TimeoutError("first attempt"),
        TimeoutError("second attempt"),
        TimeoutError("third attempt"),
        TimeoutError("retry once"),
        success,
        *[success for _ in range(19)],
    ]
    client = _FormalValidationProviderClient(responses)

    result = FullPoolFormalExperiment().run(contract, _formal_validation_adapter(client), output_dir)

    assert result.status is FullPoolRunStatus.COMPLETE
    assert result.logical_adapter_decisions == 21
    assert result.physical_provider_attempts == 24
    assert result.provider_calls == 0
    aggregates = json.loads((output_dir / "aggregates.json").read_text(encoding="utf-8"))
    accounting = aggregates["provider_accounting"]
    assert aggregates["counts"]["provider_failed_terminals"] == 1
    assert accounting["logical_judgments"] == 21
    assert accounting["physical_attempts"] == 24
    assert accounting["provider_responses"] == 20
    assert accounting["successful_decisions"] == 20
    assert accounting["usage_complete_response_count"] == 20
    assert aggregates["production_deploy_eligible"] is False
    terminals = _read_jsonl(output_dir / "terminal_rows.jsonl")
    failed = next(row for row in terminals if row["terminal_status"] == "provider_failed")
    assert failed["action"] == ""
    assert failed["request_invocations"] == 3
    ledger = _read_jsonl(execution.operational_root / "full_pool_attempt_ledger.jsonl")
    assert sum(row["event_type"] == "physical_attempt_accounted" for row in ledger) == 24


@pytest.mark.parametrize("corruption", ["ledger", "journal", "identity", "snapshot"])
def test_formal_resume_rejects_corrupt_operational_evidence_before_calls(
    tmp_path: Path,
    corruption: str,
) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = f"full-pool-validation-v1-corrupt-{corruption}"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir, active_physical_cap=2)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    first = FullPoolFormalExperiment().run(
        contract,
        _formal_validation_adapter(_FormalValidationProviderClient()),
        output_dir,
    )
    assert first.status is FullPoolRunStatus.RESUMABLE

    if corruption == "ledger":
        ledger_path = execution.operational_root / "full_pool_attempt_ledger.jsonl"
        rows = ledger_path.read_text(encoding="utf-8").splitlines()
        row = json.loads(rows[0])
        row["payload"]["pair_id"] = "crossed-pair"
        rows[0] = json.dumps(row, ensure_ascii=False, sort_keys=True)
        ledger_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    elif corruption == "journal":
        journal_path = execution.operational_root / "concurrent_message_execution_journal.jsonl"
        journal_path.write_text(journal_path.read_text(encoding="utf-8") + "{", encoding="utf-8")
    elif corruption == "identity":
        identity_path = execution.operational_root / "full_pool_execution_identity.json"
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        identity["output_identity"] = "crossed-output"
        identity_path.write_text(json.dumps(identity), encoding="utf-8")
    else:
        snapshot = next((execution.operational_root / CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR).glob("*.json"))
        snapshot.write_bytes(snapshot.read_bytes() + b" ")

    resume_client = _FormalValidationProviderClient()
    with pytest.raises(FullPoolExperimentError) as captured:
        FullPoolFormalExperiment().run(contract, _formal_validation_adapter(resume_client), output_dir)
    assert captured.value.code is FullPoolExperimentErrorCode.RUNTIME_FAILED
    assert resume_client.calls == []
    assert not output_dir.exists()


def test_formal_active_workspace_lock_fails_closed_before_calls(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-active-lock"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir, active_physical_cap=2)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    first = FullPoolFormalExperiment().run(
        contract,
        _formal_validation_adapter(_FormalValidationProviderClient()),
        output_dir,
    )
    assert first.status is FullPoolRunStatus.RESUMABLE
    identity = json.loads(
        (execution.operational_root / CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON).read_text(encoding="utf-8")
    )
    active = ConcurrentExecutionJournal.open_resume(execution.operational_root, identity=identity)
    try:
        resume_client = _FormalValidationProviderClient()
        with pytest.raises(FullPoolExperimentError) as captured:
            FullPoolFormalExperiment().run(contract, _formal_validation_adapter(resume_client), output_dir)
        assert captured.value.code is FullPoolExperimentErrorCode.RUNTIME_FAILED
        assert resume_client.calls == []
    finally:
        active.close()


def test_closed_formal_source_rejects_mutated_operational_journal_without_adapter_checks(tmp_path: Path) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-immutable-lineage"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    complete = FullPoolFormalExperiment().run(
        contract,
        _formal_validation_adapter(_FormalValidationProviderClient()),
        output_dir,
    )
    assert complete.status is FullPoolRunStatus.COMPLETE
    source_before = _file_bytes(output_dir)
    chunk = next((execution.operational_root / "concurrent_runtime_batch_spool").glob("*.json"))
    chunk.write_bytes(chunk.read_bytes() + b" ")
    wrong_adapter = _DeterministicPrimaryAdapter()

    with pytest.raises(FullPoolExperimentError) as captured:
        FullPoolFormalExperiment().run(contract, wrong_adapter, output_dir)

    assert captured.value.code is FullPoolExperimentErrorCode.SOURCE_CLOSURE_FAILED
    assert wrong_adapter.calls == []
    assert _file_bytes(output_dir) == source_before


def test_formal_partial_finalization_and_closed_source_replay_use_zero_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_dir = _fixture_dataset(tmp_path)
    output_identity = "full-pool-validation-v1-finalization-resume"
    output_dir = tmp_path / output_identity
    base_contract = _contract(dataset_dir, output_identity=output_identity)
    execution = _formal_execution_contract(base_contract, output_dir)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    first_client = _FormalValidationProviderClient()
    original_validate = full_pool_module._validate_staged_source
    failed_once = False

    def interrupt_finalization(
        source_root: Path,
        *,
        contract: FullPoolExperimentContract,
        source_identity: str,
        operational_root: Path | None = None,
    ) -> None:
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("injected source finalization interruption")
        original_validate(
            source_root,
            contract=contract,
            source_identity=source_identity,
            operational_root=operational_root,
        )

    monkeypatch.setattr(full_pool_module, "_validate_staged_source", interrupt_finalization)
    with pytest.raises(FullPoolExperimentError) as captured:
        FullPoolFormalExperiment().run(contract, _formal_validation_adapter(first_client), output_dir)
    assert captured.value.code is FullPoolExperimentErrorCode.SOURCE_CLOSURE_FAILED
    assert len(first_client.calls) == 21
    assert not output_dir.exists()

    monkeypatch.setattr(full_pool_module, "_validate_staged_source", original_validate)
    resume_client = _FormalValidationProviderClient()
    resumed = FullPoolFormalExperiment().run(contract, _formal_validation_adapter(resume_client), output_dir)
    assert resumed.status is FullPoolRunStatus.COMPLETE
    assert resume_client.calls == []
    source_before = _file_bytes(output_dir)
    operational_before = _file_bytes(execution.operational_root)
    execution.authorization.artifact_path.unlink()
    execution.qualification.artifact_path.unlink()
    execution.qualification.observed_response_artifact_path.unlink()

    wrong_adapter = _DeterministicPrimaryAdapter()
    replayed = FullPoolFormalExperiment().run(contract, wrong_adapter, output_dir)

    assert replayed == resumed
    assert wrong_adapter.calls == []
    assert _file_bytes(output_dir) == source_before
    assert _file_bytes(execution.operational_root) == operational_before


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
    assert not hasattr(llm_abm_sim, "FullPoolFormalExecutionContract")
    assert not hasattr(llm_abm_sim, "FullPoolFormalAuthorization")
    assert not hasattr(full_pool_module, "FullPoolPlanner")
    assert not hasattr(full_pool_module, "FullPoolSourceWriter")
