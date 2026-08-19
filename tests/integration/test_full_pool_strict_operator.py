from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from typing import Any, cast

import pytest

import llm_abm_sim.full_pool_source_v4 as source_v4_module
import llm_abm_sim.full_pool_strict_operator as strict_operator_module
import llm_abm_sim.full_pool_strict_replay as strict_module
from llm_abm_sim.concurrent_message_experiment import ConcurrentMessageExperimentConfig
from llm_abm_sim.decision import EngageDecision
from llm_abm_sim.full_pool_formal_experiment import FULL_POOL_FORMAL_ADAPTER_IDENTITY
from llm_abm_sim.full_pool_segmented_continuation import (
    _read_closed_full_pool_source_versioned,
)
from llm_abm_sim.full_pool_segmented_operator import SEGMENTED_PROMPT_VERSION, LiveLanePool
from llm_abm_sim.full_pool_source_v4 import (
    _ClosedStrictFullPoolSource,
    compose_strict_full_pool_result_projection,
    read_closed_strict_full_pool_source,
)
from llm_abm_sim.full_pool_strict_operator import (
    STRICT_FRESH_IMPLEMENTATION_MODULE_PATHS,
    StrictFreshAutomationOperator,
    StrictFreshExecutionManifestRequest,
    StrictFreshLiveGates,
    StrictFreshOperatorActiveError,
    create_strict_fresh_execution_manifest,
    validate_strict_fresh_execution_manifest,
)
from llm_abm_sim.full_pool_strict_replay import (
    StrictFreshReplayRequest,
    strict_formal_provider_contract,
)
from llm_abm_sim.providers.pi_subscription import (
    PI_SUBSCRIPTION_MODEL_ALIASES,
    PI_SUBSCRIPTION_PROVIDER,
)
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile
from tests.integration.test_full_pool_segmented_multibatch import _dataset
from tests.integration.test_full_pool_strict_replay import (
    _CompleteEvidenceReconciliationAdapter,
    _CompleteEvidenceStrictAdapter,
    _rejected_history,
    _request,
    _StrictAdapter,
)


class _ActionEvidenceAdapter(_CompleteEvidenceStrictAdapter):
    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        decision = super().decide(
            post,
            profile,
            peer_context,
            platform_context,
            time_step,
        )
        action = {
            "message_1": "like",
            "message_2": "comment",
            "message_3": "share",
        }[post.post_id]
        return decision.model_copy(
            update={
                "engage": True,
                "action": action,
                "probability": 0.9,
                "reason": "offline complete action evidence",
            }
        )


class _ReadyPiClient:
    ready = True
    response_timeout_seconds = 30.0
    subscription_nominal_cost_usd_total = 0.0
    safe_metadata = {
        "provider_transport": PI_SUBSCRIPTION_PROVIDER,
        "adapter_identity": FULL_POOL_FORMAL_ADAPTER_IDENTITY,
        "authentication": "local_oauth_subscription",
        "requested_model_aliases": PI_SUBSCRIPTION_MODEL_ALIASES,
        "output_token_ceiling_enforcement": "application_fail_closed",
    }

    def close(self) -> None:
        return None


def _committed_implementation_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "implementation-repo"
    repo.mkdir()
    source_repo = Path.cwd()
    for relative in STRICT_FRESH_IMPLEMENTATION_MODULE_PATHS:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_repo / relative, target)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    return repo, commit


def _rewrite_manifest(
    path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document["payload"])
    body = {
        key: value
        for key, value in document["payload"].items()
        if key != "manifest_identity"
    }
    def canonical(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    document["payload"]["manifest_identity"]["sha256"] = hashlib.sha256(
        canonical(body).encode("utf-8")
    ).hexdigest()
    document["payload_sha256"] = hashlib.sha256(
        canonical(document["payload"]).encode("utf-8")
    ).hexdigest()
    path.write_text(canonical(document) + "\n", encoding="utf-8")


def _manifest_request(tmp_path: Path) -> StrictFreshExecutionManifestRequest:
    replay = _request(tmp_path)
    operator_workspace = tmp_path / "strict-fresh-operator"
    replay = replace(replay, workspace=operator_workspace / "runtime")
    repo, commit = _committed_implementation_repo(tmp_path)
    return StrictFreshExecutionManifestRequest(
        repo_root=repo,
        manifest_path=tmp_path / "manifests" / "strict-fresh-execution.json",
        operator_workspace=operator_workspace,
        replay_request=replay,
        implementation_commit=commit,
    )


def test_fresh_execution_manifest_is_create_once_and_binds_exact_inputs(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)

    path = create_strict_fresh_execution_manifest(request)
    facts = validate_strict_fresh_execution_manifest(path)

    assert path == request.manifest_path
    assert facts.implementation_commit == request.implementation_commit
    assert facts.operator_workspace == request.operator_workspace
    assert facts.replay_request.workspace == request.operator_workspace / "runtime"
    assert facts.replay_request.provider_contract["provider_transport"] == "openai-codex"
    assert facts.replay_request.provider_contract["requested_model"] == "gpt-5.6-sol"
    assert facts.replay_request.logical_cap == 24
    assert facts.replay_request.physical_cap == 120_120
    assert facts.replay_request.max_concurrency == 10
    assert facts.provider_calls_during_composition == 0
    assert facts.production_deploy_eligible is False
    payload = cast(dict[str, Any], facts.payload)
    provider = cast(dict[str, Any], payload["provider_contract"])
    assert provider["provider"] == "Pi"
    assert provider["provider_transport"] == "openai-codex"
    assert provider["requested_model"] == "gpt-5.6-sol"
    assert provider["fresh_no_cache"] is True
    assert provider["request_contract"]["wire_api"] == "responses"
    assert provider["request_contract"]["reasoning_effort"] == "low"
    assert provider["request_contract"]["output_token_ceiling"] == 256
    assert provider["request_contract"]["timeout_seconds"] == 30.0
    assert provider["request_contract"]["max_retries"] == 2
    assert payload["messages"]["prompt_variant_id"] == "P0"
    assert payload["execution_topology"]["configured_max_concurrency"] == 10
    assert payload["accounting_caps"] == {
        "logical_cap": 24,
        "physical_cap": 120_120,
        "maximum_attempts_per_dispatch": 3,
        "maximum_dispatches_per_pair": 2,
    }
    assert payload["billing_contract"]["subscription_billed_cost_usd"] == 0.0
    assert payload["billing_contract"]["fee_ceiling_usd"] == 0.0
    assert not request.operator_workspace.exists()

    with pytest.raises(FileExistsError, match="create once"):
        create_strict_fresh_execution_manifest(request)


def test_full_pool_production_manifest_is_constructible_and_preflightable(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    dataset = _dataset(tmp_path / "full-pool", user_count=36_400)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset,
        sample_size=36_400,
        horizon=30,
        delivery_capacity=1_214,
        configuration_profile="production",
    )
    request = replace(
        request,
        replay_request=replace(
            request.replay_request,
            config=config,
            logical_cap=109_200,
        ),
    )

    path = create_strict_fresh_execution_manifest(request)
    facts = StrictFreshAutomationOperator().preflight(
        path,
        gates=StrictFreshLiveGates(
            explicit_live_authorization=True,
            external_requests_allowed=True,
            credentials_available=True,
            provider_transport="openai-codex",
            requested_model="gpt-5.6-sol",
            subscription_billed_cost_usd=0.0,
        ),
    )

    assert facts.replay_request.config.configuration_profile == "production"
    assert facts.replay_request.config.sample_size == 36_400
    assert facts.replay_request.logical_cap == 109_200
    assert not request.operator_workspace.exists()


def test_dirty_bound_implementation_is_rejected_before_adapter_factory(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    dirty_module = request.repo_root / STRICT_FRESH_IMPLEMENTATION_MODULE_PATHS[0]
    dirty_module.write_text(dirty_module.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match="dirty|drift"):
        StrictFreshAutomationOperator().run(
            path,
            gates=StrictFreshLiveGates(
                explicit_live_authorization=True,
                external_requests_allowed=True,
                credentials_available=True,
                provider_transport="openai-codex",
                requested_model="gpt-5.6-sol",
                subscription_billed_cost_usd=0.0,
            ),
            adapter_factory=lambda lane_id: (
                factory_calls.append(lane_id) or _CompleteEvidenceStrictAdapter(lane_id)
            ),
        )

    assert factory_calls == []
    assert not request.operator_workspace.exists()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["provider_contract"].__setitem__(
            "requested_model", "crossed-model"
        ),
        lambda payload: payload["accounting_caps"].__setitem__("physical_cap", 1),
        lambda payload: payload["output_paths"].__setitem__(
            "runtime_workspace", payload["dataset"]["root"]
        ),
    ],
)
def test_tampered_model_caps_or_crossed_path_is_rejected_before_adapter_factory(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    _rewrite_manifest(path, mutate)
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match="manifest|Provider|crossed|workspace|caps"):
        StrictFreshAutomationOperator().run(
            path,
            gates=StrictFreshLiveGates(
                explicit_live_authorization=True,
                external_requests_allowed=True,
                credentials_available=True,
                provider_transport="openai-codex",
                requested_model="gpt-5.6-sol",
                subscription_billed_cost_usd=0.0,
            ),
            adapter_factory=lambda lane_id: (
                factory_calls.append(lane_id) or _CompleteEvidenceStrictAdapter(lane_id)
            ),
        )

    assert factory_calls == []


def test_manifest_creation_rejects_overlapping_workspace_and_wrong_commit(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    overlap = replace(
        request,
        manifest_path=request.operator_workspace / "execution-manifest.json",
    )
    with pytest.raises(ValueError, match="overlap|independent"):
        create_strict_fresh_execution_manifest(overlap)

    wrong_commit = replace(request, implementation_commit="0" * 40)
    with pytest.raises(ValueError, match="commit"):
        create_strict_fresh_execution_manifest(wrong_commit)

    wrong_caps = replace(
        request,
        replay_request=replace(request.replay_request, physical_cap=1),
    )
    with pytest.raises(ValueError, match="caps"):
        create_strict_fresh_execution_manifest(wrong_caps)


def test_same_manifest_operator_attempts_are_audited_and_replay_captured_source_without_calls(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    gates = StrictFreshLiveGates(
        explicit_live_authorization=True,
        external_requests_allowed=True,
        credentials_available=True,
        provider_transport="openai-codex",
        requested_model="gpt-5.6-sol",
        subscription_billed_cost_usd=0.0,
    )
    factory_calls: list[int] = []

    first = StrictFreshAutomationOperator().run(
        path,
        gates=gates,
        adapter_factory=lambda lane_id: (
            factory_calls.append(lane_id) or _CompleteEvidenceStrictAdapter(lane_id)
        ),
    )

    assert first.source_root == request.replay_request.workspace / "source-v4"
    assert first.source_manifest_sha256 is not None
    assert factory_calls == list(range(10))
    source_root = first.source_root
    assert source_root is not None
    source_manifest = json.loads(
        (source_root / "manifest.json").read_text(encoding="utf-8")
    )
    manifest_facts = validate_strict_fresh_execution_manifest(path)
    assert source_manifest["operator_execution"] == {
        "attempt_ledger_identity_sha256": manifest_facts.attempt_ledger_identity_sha256,
        "attempt_ledger_path": str(manifest_facts.attempt_ledger_path),
        "execution_manifest_identity_sha256": manifest_facts.manifest_identity_sha256,
        "execution_manifest_path": str(path),
        "execution_manifest_sha256": manifest_facts.manifest_sha256,
    }
    assert (source_root / "operator" / "execution-manifest.json").read_bytes() == path.read_bytes()
    ledger_path = request.operator_workspace / "strict_fresh_operator_attempt_ledger.jsonl"
    records = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert [record["event_type"] for record in records] == [
        "attempt_started",
        "attempt_terminal",
    ]

    def tripwire(_: int) -> _CompleteEvidenceStrictAdapter:
        raise AssertionError("same-manifest replay must not create an Adapter")

    replay = StrictFreshAutomationOperator().run(
        path,
        gates=gates,
        adapter_factory=tripwire,
    )

    assert replay.source_manifest_sha256 == first.source_manifest_sha256
    records = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert [record["event_type"] for record in records] == [
        "attempt_started",
        "attempt_terminal",
        "attempt_resumed",
        "attempt_terminal",
    ]
    assert [record["sequence"] for record in records] == [1, 2, 3, 4]


def test_second_operator_owner_is_rejected_before_adapter_factory(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    gates = StrictFreshLiveGates(
        explicit_live_authorization=True,
        external_requests_allowed=True,
        credentials_available=True,
        provider_transport="openai-codex",
        requested_model="gpt-5.6-sol",
        subscription_billed_cost_usd=0.0,
    )
    first_factory_entered = Event()
    release_first_factory = Event()
    first_errors: list[BaseException] = []

    def first_factory(lane_id: int) -> _CompleteEvidenceStrictAdapter:
        if lane_id == 0:
            first_factory_entered.set()
            assert release_first_factory.wait(timeout=10)
        return _CompleteEvidenceStrictAdapter(lane_id)

    def first_owner() -> None:
        try:
            StrictFreshAutomationOperator().run(
                path,
                gates=gates,
                adapter_factory=first_factory,
            )
        except BaseException as exc:  # pragma: no cover - asserted in the parent thread.
            first_errors.append(exc)

    thread = Thread(target=first_owner)
    thread.start()
    assert first_factory_entered.wait(timeout=10)
    second_factory_calls: list[int] = []
    try:
        with pytest.raises(StrictFreshOperatorActiveError, match="active owner"):
            StrictFreshAutomationOperator().run(
                path,
                gates=gates,
                adapter_factory=lambda lane_id: (
                    second_factory_calls.append(lane_id)
                    or _CompleteEvidenceStrictAdapter(lane_id)
                ),
            )
    finally:
        release_first_factory.set()
        thread.join(timeout=30)

    assert not thread.is_alive()
    assert first_errors == []
    assert second_factory_calls == []


def test_released_lock_resumes_same_manifest_after_source_closure_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    gates = StrictFreshLiveGates(
        explicit_live_authorization=True,
        external_requests_allowed=True,
        credentials_available=True,
        provider_transport="openai-codex",
        requested_model="gpt-5.6-sol",
        subscription_billed_cost_usd=0.0,
    )
    real_write = strict_module._write_source_v4_rows

    def crash_after_rows(*args: object, **kwargs: object) -> None:
        real_write(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("offline operator source closure crash")

    monkeypatch.setattr(strict_module, "_write_source_v4_rows", crash_after_rows)
    with pytest.raises(RuntimeError, match="source closure crash"):
        StrictFreshAutomationOperator().run(
            path,
            gates=gates,
            adapter_factory=_CompleteEvidenceStrictAdapter,
        )
    monkeypatch.setattr(strict_module, "_write_source_v4_rows", real_write)

    def tripwire(_: int) -> _CompleteEvidenceStrictAdapter:
        raise AssertionError("captured pairs must not be called after released-lock resume")

    result = StrictFreshAutomationOperator().run(
        path,
        gates=gates,
        adapter_factory=tripwire,
    )

    assert result.source_root == request.replay_request.workspace / "source-v4"
    records = [
        json.loads(line)
        for line in (
            request.operator_workspace / "strict_fresh_operator_attempt_ledger.jsonl"
        )
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    assert [record["event_type"] for record in records] == [
        "attempt_started",
        "attempt_resumable",
        "attempt_resumed",
        "attempt_terminal",
    ]


def test_persisted_source_v4_consumer_rebuilds_facts_and_nine_row_projection(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    result = StrictFreshAutomationOperator().run(
        path,
        gates=StrictFreshLiveGates(
            explicit_live_authorization=True,
            external_requests_allowed=True,
            credentials_available=True,
            provider_transport="openai-codex",
            requested_model="gpt-5.6-sol",
            subscription_billed_cost_usd=0.0,
        ),
        adapter_factory=_CompleteEvidenceStrictAdapter,
    )
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None

    source = read_closed_strict_full_pool_source(
        result.source_root,
        manifest_sha256=result.source_manifest_sha256,
    )
    projection = compose_strict_full_pool_result_projection(source)

    assert source.facts.distinct_users == 8
    assert source.facts.logical_pairs == 24
    assert source.facts.committed_batches == 2
    assert source.facts.provider_failed_final_count == 0
    assert source.facts.observed_model_counts == {"gpt-5.6-sol": 24}
    assert source.facts.usage_complete_response_count == 24
    assert source.facts.original_dispatch_count == 24
    assert source.facts.reconciliation_dispatch_count == 0
    assert source.facts.maximum_dispatches_for_one_pair == 1
    assert source.facts.external_request_invocations == 0
    assert source.facts.production_deploy_eligible is False
    assert len(projection.rows) == 9
    assert projection.total_exposure == 24
    assert list(projection.rows[0]) == [
        "Run",
        "Message",
        "Segment",
        "Total Likes",
        "Total Comments",
        "Total Shares",
        "Exposure",
    ]
    assert [(row["Segment"], row["Message"], row["Run"]) for row in projection.rows] == [
        (segment, message, 1)
        for segment in ("S1", "S2", "S3")
        for message in ("M1", "M2", "M3")
    ]
    assert projection.csv_bytes.startswith(
        b"Run,Message,Segment,Total Likes,Total Comments,Total Shares,Exposure\n"
    )
    assert "旧 mixed trajectory 未参与结果" in projection.lineage_markdown
    dispatched = _read_closed_full_pool_source_versioned(
        result.source_root,
        manifest_sha256=result.source_manifest_sha256,
    )
    assert isinstance(dispatched, _ClosedStrictFullPoolSource)
    assert dispatched.facts.source_manifest_sha256 == result.source_manifest_sha256


def test_source_v4_projection_counts_only_final_success_actions_and_includes_ignore_exposure(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    result = StrictFreshAutomationOperator().run(
        path,
        gates=StrictFreshLiveGates(
            explicit_live_authorization=True,
            external_requests_allowed=True,
            credentials_available=True,
            provider_transport="openai-codex",
            requested_model="gpt-5.6-sol",
            subscription_billed_cost_usd=0.0,
        ),
        adapter_factory=_ActionEvidenceAdapter,
    )
    assert result.source is not None
    assert result.projection is not None

    for row in result.projection.rows:
        exposure = cast(int, row["Exposure"])
        if row["Message"] == "M1":
            assert row["Total Likes"] == exposure
            assert row["Total Comments"] == 0
            assert row["Total Shares"] == 0
        elif row["Message"] == "M2":
            assert row["Total Likes"] == 0
            assert row["Total Comments"] == exposure
            assert row["Total Shares"] == 0
        else:
            assert row["Total Likes"] == 0
            assert row["Total Comments"] == 0
            assert row["Total Shares"] == exposure
    assert result.projection.total_exposure == 24


def test_source_v4_consumer_proves_bounded_original_and_reconciliation_dispatches(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    result = StrictFreshAutomationOperator().run(
        path,
        gates=StrictFreshLiveGates(
            explicit_live_authorization=True,
            external_requests_allowed=True,
            credentials_available=True,
            provider_transport="openai-codex",
            requested_model="gpt-5.6-sol",
            subscription_billed_cost_usd=0.0,
        ),
        adapter_factory=_CompleteEvidenceReconciliationAdapter,
    )
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None

    source = read_closed_strict_full_pool_source(
        result.source_root,
        manifest_sha256=result.source_manifest_sha256,
    )

    assert source.facts.logical_pairs == 24
    assert source.facts.original_dispatch_count == 24
    assert source.facts.reconciliation_dispatch_count == 1
    assert source.facts.maximum_dispatches_for_one_pair == 2
    assert source.facts.maximum_request_invocations_for_one_dispatch == 3
    assert source.facts.settled_actual_attempts == 27
    assert source.facts.charged_physical_attempts == 27
    assert source.facts.provider_failed_final_count == 0


def test_strict_status_persists_runtime_production_eligibility(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    result = StrictFreshAutomationOperator().run(
        path,
        gates=StrictFreshLiveGates(
            explicit_live_authorization=True,
            external_requests_allowed=True,
            credentials_available=True,
            provider_transport="openai-codex",
            requested_model="gpt-5.6-sol",
            subscription_billed_cost_usd=0.0,
        ),
        adapter_factory=_CompleteEvidenceStrictAdapter,
    )
    eligible = replace(result.runtime, production_deploy_eligible=True)

    strict_module._write_status(request.replay_request.workspace, eligible)

    status = json.loads(
        (request.replay_request.workspace / "strict_fresh_replay_status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["production_deploy_eligible"] is True


def test_consumer_rejection_is_appended_after_runtime_terminal_and_can_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    gates = StrictFreshLiveGates(
        explicit_live_authorization=True,
        external_requests_allowed=True,
        credentials_available=True,
        provider_transport="openai-codex",
        requested_model="gpt-5.6-sol",
        subscription_billed_cost_usd=0.0,
    )
    real_consumer = source_v4_module.read_closed_strict_full_pool_source

    def reject_consumer(*_args: object, **_kwargs: object) -> object:
        raise ValueError("offline persisted consumer rejection")

    monkeypatch.setattr(
        source_v4_module,
        "read_closed_strict_full_pool_source",
        reject_consumer,
    )
    with pytest.raises(ValueError, match="consumer rejection"):
        StrictFreshAutomationOperator().run(
            path,
            gates=gates,
            adapter_factory=_CompleteEvidenceStrictAdapter,
        )
    ledger_path = request.operator_workspace / "strict_fresh_operator_attempt_ledger.jsonl"
    records = [json.loads(line) for line in ledger_path.read_text().splitlines() if line]
    assert [record["event_type"] for record in records] == [
        "attempt_started",
        "attempt_terminal",
        "source_v4_consumer_rejected",
    ]
    assert records[-1]["payload"]["reason_class"] == "builtins.ValueError"

    monkeypatch.setattr(
        source_v4_module,
        "read_closed_strict_full_pool_source",
        real_consumer,
    )

    def tripwire(_: int) -> _CompleteEvidenceStrictAdapter:
        raise AssertionError("consumer-rejected resume must not call a captured pair")

    resumed = StrictFreshAutomationOperator().run(
        path,
        gates=gates,
        adapter_factory=tripwire,
    )
    assert resumed.source is not None
    records = [json.loads(line) for line in ledger_path.read_text().splitlines() if line]
    assert [record["event_type"] for record in records[-2:]] == [
        "attempt_resumed",
        "attempt_terminal",
    ]


def test_strict_stop_is_terminal_non_deployable_and_creates_no_source_v4(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    result = StrictFreshAutomationOperator().run(
        path,
        gates=StrictFreshLiveGates(
            explicit_live_authorization=True,
            external_requests_allowed=True,
            credentials_available=True,
            provider_transport="openai-codex",
            requested_model="gpt-5.6-sol",
            subscription_billed_cost_usd=0.0,
        ),
        adapter_factory=lambda lane_id: _StrictAdapter(
            lane_id,
            [],
            initial_outcome="provider_failed",
            reconciliation_outcome="provider_failed",
        ),
    )

    assert result.runtime.status.value == "strict_stop_provider_failed"
    assert result.source is None
    assert result.projection is None
    assert result.production_deploy_eligible is False
    assert not (request.replay_request.workspace / "source-v4").exists()
    records = [
        json.loads(line)
        for line in (
            request.operator_workspace / "strict_fresh_operator_attempt_ledger.jsonl"
        )
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    assert records[-1]["event_type"] == "attempt_terminal"
    assert records[-1]["payload"]["status"] == "strict_stop_provider_failed"


def test_source_v4_consumer_rejects_tampered_operator_attempt_chain(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    result = StrictFreshAutomationOperator().run(
        path,
        gates=StrictFreshLiveGates(
            explicit_live_authorization=True,
            external_requests_allowed=True,
            credentials_available=True,
            provider_transport="openai-codex",
            requested_model="gpt-5.6-sol",
            subscription_billed_cost_usd=0.0,
        ),
        adapter_factory=_CompleteEvidenceStrictAdapter,
    )
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None
    ledger_path = request.operator_workspace / "strict_fresh_operator_attempt_ledger.jsonl"
    records = ledger_path.read_text(encoding="utf-8").splitlines()
    terminal = json.loads(records[-1])
    terminal["checksum"] = "0" * 64
    records[-1] = json.dumps(
        terminal,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    ledger_path.write_text("\n".join(records) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="attempt ledger|checksum|sequence"):
        read_closed_strict_full_pool_source(
            result.source_root,
            manifest_sha256=result.source_manifest_sha256,
        )


def test_source_v4_consumer_rejects_rehashed_mixed_terminal_injection(
    tmp_path: Path,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    result = StrictFreshAutomationOperator().run(
        path,
        gates=StrictFreshLiveGates(
            explicit_live_authorization=True,
            external_requests_allowed=True,
            credentials_available=True,
            provider_transport="openai-codex",
            requested_model="gpt-5.6-sol",
            subscription_billed_cost_usd=0.0,
        ),
        adapter_factory=_CompleteEvidenceStrictAdapter,
    )
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None
    terminal_path = result.source_root / "terminal_rows.jsonl"
    rows = terminal_path.read_text(encoding="utf-8").splitlines()
    terminal = json.loads(rows[0])
    terminal["terminal_status"] = "provider_failed"
    terminal["provider_status"] = "provider_failed"
    rows[0] = json.dumps(
        terminal,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    terminal_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    terminal_sha = hashlib.sha256(terminal_path.read_bytes()).hexdigest()
    manifest_path = result.source_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["row_hashes"]["terminal_rows.jsonl"] = terminal_sha
    for artifact in manifest["artifacts"]:
        if artifact["relative_path"] == "terminal_rows.jsonl":
            artifact["sha256"] = terminal_sha
            artifact["bytes"] = terminal_path.stat().st_size
    manifest["source_hash"] = hashlib.sha256(
        json.dumps(
            manifest["artifacts"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    crossed_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="spool|mixed|terminal|attempt"):
        read_closed_strict_full_pool_source(
            result.source_root,
            manifest_sha256=crossed_hash,
        )


@pytest.mark.full_scale_rehearsal
def test_full_scale_same_manifest_operator_and_consumer_close_zero_call_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm_abm_sim._concurrent_runtime_spool as spool_module
    import llm_abm_sim.concurrent_execution_journal as journal_module
    import llm_abm_sim.concurrent_message_experiment as experiment_module
    import llm_abm_sim.durable_pair_settlement as settlement_module

    root = tmp_path / "strict-operator-full-scale"
    root.mkdir()
    monkeypatch.setattr(strict_module.os, "fsync", lambda _descriptor: None)
    for module in (
        settlement_module,
        spool_module,
        journal_module,
        experiment_module,
        strict_module,
    ):
        monkeypatch.setattr(module, "safe_data", lambda value: value)
    dataset = _dataset(root, user_count=36_400)
    users_path = dataset / "users.csv"
    with users_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        rows = list(reader)
    assert fieldnames is not None
    for index, row in enumerate(rows):
        if index < 15_616:
            row["latent_class"] = "class_1"
        elif index < 15_616 + 15_070:
            row["latent_class"] = "class_2"
        else:
            row["latent_class"] = "class_3"
    with users_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    operator_workspace = root / "operator"
    replay_request = StrictFreshReplayRequest(
        config=ConcurrentMessageExperimentConfig(
            dataset_dir=dataset,
            sample_size=36_400,
            horizon=30,
            delivery_capacity=1_214,
            configuration_profile="production",
        ),
        workspace=operator_workspace / "runtime",
        replay_id="offline-strict-operator-full-scale-v1",
        provider_contract=strict_formal_provider_contract(),
        rejected_history=_rejected_history(root),
        seed_top_k_per_proxy=10,
        logical_cap=109_200,
        physical_cap=120_120,
        max_concurrency=10,
    )
    repo, commit = _committed_implementation_repo(root)
    manifest_request = StrictFreshExecutionManifestRequest(
        repo_root=repo,
        manifest_path=root / "manifest" / "strict-fresh-execution.json",
        operator_workspace=operator_workspace,
        replay_request=replay_request,
        implementation_commit=commit,
    )
    manifest_path = create_strict_fresh_execution_manifest(manifest_request)
    gates = StrictFreshLiveGates(
        explicit_live_authorization=True,
        external_requests_allowed=True,
        credentials_available=True,
        provider_transport="openai-codex",
        requested_model="gpt-5.6-sol",
        subscription_billed_cost_usd=0.0,
    )
    adapters: dict[int, _CompleteEvidenceStrictAdapter] = {}

    def factory(lane_id: int) -> _CompleteEvidenceStrictAdapter:
        adapter = _CompleteEvidenceStrictAdapter(lane_id)
        adapters[lane_id] = adapter
        return adapter

    result = StrictFreshAutomationOperator().run(
        manifest_path,
        gates=gates,
        adapter_factory=factory,
    )

    assert result.runtime.logical_count == 109_200
    assert result.runtime.committed_batch_count == 30
    assert result.runtime.charged_physical_attempts == 109_200
    assert result.runtime.charged_physical_attempts <= 120_120
    assert result.source is not None
    assert result.source.facts.distinct_users == 36_400
    assert result.source.facts.logical_pairs == 109_200
    assert result.source.facts.committed_batches == 30
    assert result.source.facts.observed_model_counts == {"gpt-5.6-sol": 109_200}
    assert result.source.facts.segment_denominators == {
        "class_1": 15_616,
        "class_2": 15_070,
        "class_3": 5_714,
    }
    assert result.source.facts.external_request_invocations == 0
    assert result.source.facts.production_deploy_eligible is False
    assert result.projection is not None
    assert result.projection.total_exposure == 109_200
    assert sum(adapter.request_invocations for adapter in adapters.values()) == 109_200
    assert sum(adapter.external_request_invocations for adapter in adapters.values()) == 0

    def tripwire(_: int) -> _CompleteEvidenceStrictAdapter:
        raise AssertionError("full-scale same-manifest replay must not create an Adapter")

    replay = StrictFreshAutomationOperator().run(
        manifest_path,
        gates=gates,
        adapter_factory=tripwire,
    )
    assert replay.source_manifest_sha256 == result.source_manifest_sha256
    assert replay.source is not None
    assert replay.source.facts.logical_pairs == 109_200
    assert replay.projection is not None
    assert replay.projection.rows_sha256 == result.projection.rows_sha256


def test_full_scale_validation_profile_is_rejected_by_live_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _manifest_request(tmp_path)
    path = create_strict_fresh_execution_manifest(request)
    facts = validate_strict_fresh_execution_manifest(path)
    validation_config = facts.replay_request.config.model_copy(
        update={
            "sample_size": 36_400,
            "horizon": 30,
            "delivery_capacity": 1_214,
            "configuration_profile": "validation",
        }
    )
    crossed_facts = replace(
        facts,
        replay_request=replace(
            facts.replay_request,
            config=validation_config,
            logical_cap=109_200,
        ),
    )
    monkeypatch.setattr(
        strict_operator_module,
        "validate_strict_fresh_execution_manifest",
        lambda *_args, **_kwargs: crossed_facts,
    )

    with pytest.raises(ValueError, match="production profile|production topology"):
        StrictFreshAutomationOperator().preflight(
            path,
            gates=StrictFreshLiveGates(
                explicit_live_authorization=True,
                external_requests_allowed=True,
                credentials_available=True,
                provider_transport="openai-codex",
                requested_model="gpt-5.6-sol",
                subscription_billed_cost_usd=0.0,
            ),
        )


def test_strict_runtime_accepts_production_live_lane_pool_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    monkeypatch.setenv("LLM_ABM_RUN_FULL_POOL_SEGMENTED_CONTINUATION", "1")
    pool = LiveLanePool(
        prompt_version=SEGMENTED_PROMPT_VERSION,
        client_factory=lambda **_kwargs: _ReadyPiClient(),  # type: ignore[arg-type]
    )
    try:
        adapter = pool.adapter_factory(0)
        strict_module._validate_adapter(
            adapter,
            strict_module.strict_formal_provider_contract(),
        )
    finally:
        pool.close()
