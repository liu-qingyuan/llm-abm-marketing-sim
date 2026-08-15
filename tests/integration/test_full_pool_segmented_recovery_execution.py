from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import llm_abm_sim.full_pool_segmented_continuation as continuation_module
from llm_abm_sim.decision import EngageDecision, ProviderResponseProvenanceUnknown
from llm_abm_sim.full_pool_segmented_recovery import FullPoolSegmentedRecoveryPreflight
from llm_abm_sim.full_pool_segmented_recovery_execution import (
    FullPoolSegmentedRecovery,
    SegmentedRecoveryExecutionRequest,
)
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile
from tests.integration.test_full_pool_segmented_multibatch import _LaneAdapter
from tests.integration.test_full_pool_segmented_recovery import _failed_run


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_authorization(
    path: Path,
    *,
    plan_path: Path,
    recovery_id: str,
    recovery_workspace: Path,
    expires_at: str = "2026-08-16T00:00:00+00:00",
    mutate: Any | None = None,
) -> None:
    plan_sha256 = _sha(plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))["payload"]
    identity = plan["recovery_identity"]
    execution = plan["execution_contract"]
    accounting = plan["accounting"]
    unresolved = plan["recovery_snapshot"]["unresolved_pairs"]
    payload = {
        "schema_version": "full-pool-segmented-recovery-human-authorization-v1",
        "authorization_id": "offline-human-authorization-v1",
        "authorization_reference": "GitHub issue 208 deterministic fixture approval",
        "authorized_at": "2026-08-15T00:00:00+00:00",
        "expires_at": expires_at,
        "scope": "retry-two-unresolved-and-complete-source-v2",
        "recovery_plan_sha256": plan_sha256,
        "recovery_plan_identity_hash": identity["identity_hash"],
        "failed_continuation_identity_hash": identity["failed_continuation_identity_hash"],
        "unresolved_pair_ids": [row["pair_id"] for row in unresolved],
        "configured_max_concurrency": 10,
        "prompt_version": execution["prompt_version"],
        "provider_contract_sha256": execution["provider_contract_sha256"],
        "prompt_contract_sha256": execution["prompt_contract_sha256"],
        "requested_model": "gpt-5.6-sol",
        "required_observed_model": "gpt-5.6-sol",
        "maximum_attempts_per_dispatch": 3,
        "uncertainty_physical_charge": accounting["unresolved_uncertainty_physical_charge"],
        "logical_cap": accounting["logical_cap"],
        "physical_cap": accounting["physical_cap"],
        "historical_logical_count": accounting["historical_logical_count"],
        "historical_physical_attempts": accounting["historical_physical_attempts"],
        "recovery_id": recovery_id,
        "recovery_workspace": str(recovery_workspace.resolve()),
        "retry_authorized": True,
        "production_deploy_eligible": False,
    }
    if mutate is not None:
        mutate(payload)
    envelope = {
        "schema_version": "full-pool-segmented-recovery-human-authorization-envelope-v1",
        "payload": payload,
        "payload_sha256": hashlib.sha256(_canonical(payload).encode()).hexdigest(),
    }
    path.write_text(_canonical(envelope) + "\n", encoding="utf-8")


def _prepared_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SegmentedRecoveryExecutionRequest, dict[str, Any]]:
    plan_request, failed = _failed_run(
        tmp_path,
        monkeypatch,
        delivery_capacity=5,
        sample_size=10,
        fail_lane_id=8,
    )
    plan_result = FullPoolSegmentedRecoveryPreflight().prepare(plan_request)
    recovery_workspace = tmp_path / "recovered-continuation"
    recovery_id = "offline-dual-unresolved-recovery-v1"
    authorization_path = tmp_path / "human-authorization.json"
    _write_authorization(
        authorization_path,
        plan_path=plan_result.artifact_path,
        recovery_id=recovery_id,
        recovery_workspace=recovery_workspace,
    )
    return (
        SegmentedRecoveryExecutionRequest(
            recovery_plan_path=plan_result.artifact_path,
            recovery_plan_sha256=plan_result.artifact_sha256,
            authorization_path=authorization_path,
            authorization_sha256=_sha(authorization_path),
            recovery_id=recovery_id,
            recovery_workspace=recovery_workspace,
        ),
        failed,
    )


def _clock() -> datetime:
    return datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda payload: payload.__setitem__("recovery_plan_sha256", "0" * 64), "recovery plan"),
        (lambda payload: payload.__setitem__("unresolved_pair_ids", list(reversed(payload["unresolved_pair_ids"]))), "unresolved"),
        (lambda payload: payload.__setitem__("configured_max_concurrency", 5), "concurrency"),
        (lambda payload: payload.__setitem__("expires_at", "2026-08-15T01:00:00+00:00"), "expired"),
        (lambda payload: payload.__setitem__("recovery_id", "crossed-recovery"), "recovery identity"),
    ],
)
def test_authorization_drift_fails_before_adapter_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Any,
    match: str,
) -> None:
    request, _failed = _prepared_recovery(tmp_path, monkeypatch)
    _write_authorization(
        request.authorization_path,
        plan_path=request.recovery_plan_path,
        recovery_id=request.recovery_id,
        recovery_workspace=request.recovery_workspace,
        mutate=mutate,
    )
    crossed = request.model_copy(update={"authorization_sha256": _sha(request.authorization_path)})
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match=match):
        FullPoolSegmentedRecovery(now=_clock).run(
            crossed,
            adapter_factory=lambda lane_id: factory_calls.append(lane_id) or _LaneAdapter([]),
        )

    assert factory_calls == []
    assert not request.recovery_workspace.exists()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_recovers_only_two_unresolved_pairs_and_closes_lineage_bound_source_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, failed = _prepared_recovery(tmp_path, monkeypatch)
    plan = json.loads(request.recovery_plan_path.read_text(encoding="utf-8"))["payload"]
    unresolved_ids = [
        row["pair_id"] for row in plan["recovery_snapshot"]["unresolved_pairs"]
    ]
    failed_request = failed["request"]
    protected = {
        path: path.read_bytes()
        for root in (
            failed_request.frozen_prefix_workspace,
            failed_request.continuation_workspace,
            request.recovery_plan_path.parent,
        )
        for path in root.rglob("*")
        if path.is_file()
    }
    protected[request.authorization_path] = request.authorization_path.read_bytes()
    calls: list[str] = []
    factory_calls: list[int] = []

    result = FullPoolSegmentedRecovery(now=_clock).run(
        request,
        adapter_factory=lambda lane_id: factory_calls.append(lane_id)
        or _LaneAdapter(calls),
    )

    assert result.status == "complete"
    assert factory_calls == list(range(10))
    assert calls[:2] == unresolved_ids
    assert len(calls) == 7
    assert result.recovered_pair_ids == tuple(unresolved_ids)
    assert result.unknown_pair_ids == ()
    assert result.logical_count == 30
    assert result.imported_durable_terminal_count == 23
    assert result.historical_physical_attempts == failed["result"].physical_attempt_count
    assert result.uncertainty_physical_charge == 6
    assert result.retry_physical_attempts == 2
    assert result.continuation_physical_attempts == 5
    assert result.physical_attempt_count == failed["result"].physical_attempt_count + 13
    assert result.provider_calls == 0
    assert result.production_deploy_eligible is False
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None

    source = result.source_root
    pair_rows = _read_jsonl(source / "pair_rows.jsonl")
    terminal_rows = _read_jsonl(source / "terminal_rows.jsonl")
    steps = _read_jsonl(source / "steps.jsonl")
    assert len(pair_rows) == len(terminal_rows) == 30
    assert len({row["pair_id"] for row in terminal_rows}) == 30
    assert [row["pair_id"] for row in terminal_rows if row["reconciliation_retry"]] == unresolved_ids
    assert [row["time_step"] for row in steps] == [0, 1, 2]
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["recovery_lineage"]["recovery_plan_sha256"] == request.recovery_plan_sha256
    assert manifest["recovery_lineage"]["human_authorization_sha256"] == request.authorization_sha256
    assert manifest["recovery_lineage"]["failed_continuation_identity_hash"] == plan[
        "recovery_identity"
    ]["failed_continuation_identity_hash"]
    assert manifest["recovery_lineage"]["qualification_artifact_sha256"] == plan[
        "failed_run_lineage"
    ]["qualification_artifact_sha256"]
    assert manifest["recovery_accounting"] == {
        "logical_cap": 109_200,
        "historical_logical_count": failed["result"].logical_count,
        "logical_retry_charge": 0,
        "fresh_logical_count": 5,
        "logical_count": 30,
        "physical_cap": 120_120,
        "historical_physical_attempts": failed["result"].physical_attempt_count,
        "unresolved_uncertainty_physical_charge": 6,
        "retry_actual_physical_attempts": 2,
        "continuation_actual_physical_attempts": 5,
        "physical_attempt_count": failed["result"].physical_attempt_count + 13,
    }
    assert (source / "recovery-plan.json").read_bytes() == request.recovery_plan_path.read_bytes()
    assert (source / "human-authorization.json").read_bytes() == request.authorization_path.read_bytes()
    assert _sha(source / "concurrency_qualification.json") == plan["failed_run_lineage"][
        "qualification_artifact_sha256"
    ]
    assert {path: path.read_bytes() for path in protected} == protected

    (request.recovery_workspace / "segmented_recovery_status.json").unlink()
    (request.recovery_workspace / "segmented_continuation_status.json").unlink()
    replay_factory_calls: list[int] = []
    replay = FullPoolSegmentedRecovery(now=_clock).run(
        request,
        adapter_factory=lambda lane_id: replay_factory_calls.append(lane_id)
        or _LaneAdapter([]),
    )
    assert replay == result
    assert replay_factory_calls == []


class _UnknownRetryAdapter(_LaneAdapter):
    def __init__(self, lane_id: int, calls: list[str]) -> None:
        super().__init__(calls)
        self.lane_id = lane_id

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
        if self.lane_id == 0 and time_step == 1:
            raise ProviderResponseProvenanceUnknown("offline recovery retry unknown")
        return decision


def test_new_retry_unknown_closes_recovery_and_never_auto_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _failed = _prepared_recovery(tmp_path, monkeypatch)
    plan = json.loads(request.recovery_plan_path.read_text(encoding="utf-8"))["payload"]
    unresolved_ids = tuple(
        row["pair_id"] for row in plan["recovery_snapshot"]["unresolved_pairs"]
    )
    calls: list[str] = []
    factory_calls: list[int] = []

    result = FullPoolSegmentedRecovery(now=_clock).run(
        request,
        adapter_factory=lambda lane_id: factory_calls.append(lane_id)
        or _UnknownRetryAdapter(lane_id, calls),
    )

    assert result.status == "reconciliation_required"
    assert result.source_root is None
    assert result.unknown_pair_ids == unresolved_ids
    assert result.recovered_pair_ids == ()
    assert result.retry_physical_attempts == 2
    assert result.logical_count == plan["accounting"]["historical_logical_count"]
    assert factory_calls == list(range(10))
    assert calls == list(unresolved_ids)

    replay_factory_calls: list[int] = []
    replay = FullPoolSegmentedRecovery(now=_clock).run(
        request,
        adapter_factory=lambda lane_id: replay_factory_calls.append(lane_id)
        or _LaneAdapter([]),
    )
    assert replay == result
    assert replay_factory_calls == []


def test_failed_qualification_mutation_is_rejected_before_adapter_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, failed = _prepared_recovery(tmp_path, monkeypatch)
    qualification = failed["request"].qualification_artifact
    qualification.write_bytes(qualification.read_bytes() + b" ")
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match="qualification artifact changed"):
        FullPoolSegmentedRecovery(now=_clock).run(
            request,
            adapter_factory=lambda lane_id: factory_calls.append(lane_id)
            or _LaneAdapter([]),
        )

    assert factory_calls == []
    assert not request.recovery_workspace.exists()


def test_copied_recovery_or_qualification_tamper_blocks_zero_call_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _failed = _prepared_recovery(tmp_path, monkeypatch)
    result = FullPoolSegmentedRecovery(now=_clock).run(
        request,
        adapter_factory=lambda _lane_id: _LaneAdapter([]),
    )
    assert result.source_root is not None
    copied = result.source_root / "concurrency_qualification.json"
    copied.write_bytes(copied.read_bytes() + b" ")
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match="artifact hash is crossed"):
        FullPoolSegmentedRecovery(now=_clock).run(
            request,
            adapter_factory=lambda lane_id: factory_calls.append(lane_id)
            or _LaneAdapter([]),
        )

    assert factory_calls == []


def test_source_rename_interruption_recovers_without_adapter_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _failed = _prepared_recovery(tmp_path, monkeypatch)
    real_replace = continuation_module.os.replace
    interrupted = False

    def interrupt_source_rename(source: str | Path, target: str | Path) -> None:
        nonlocal interrupted
        if Path(target).name == "source-v2" and not interrupted:
            interrupted = True
            raise OSError("offline source rename interruption")
        real_replace(source, target)

    monkeypatch.setattr(continuation_module.os, "replace", interrupt_source_rename)
    with pytest.raises(OSError, match="source rename interruption"):
        FullPoolSegmentedRecovery(now=_clock).run(
            request,
            adapter_factory=lambda _lane_id: _LaneAdapter([]),
        )
    assert (request.recovery_workspace / ".source-v2.staging").is_dir()
    monkeypatch.setattr(continuation_module.os, "replace", real_replace)
    factory_calls: list[int] = []

    recovered = FullPoolSegmentedRecovery(now=_clock).run(
        request,
        adapter_factory=lambda lane_id: factory_calls.append(lane_id)
        or _LaneAdapter([]),
    )

    assert recovered.status == "complete"
    assert recovered.source_root is not None and recovered.source_root.is_dir()
    assert factory_calls == []
