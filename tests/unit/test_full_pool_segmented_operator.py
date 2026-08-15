from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from llm_abm_sim.full_pool_segmented_continuation import SegmentedQualificationWave
from llm_abm_sim.full_pool_segmented_operator import (
    SEGMENTED_AUTHORIZATION_REFERENCE,
    SEGMENTED_IMPLEMENTATION_COMMIT,
    SEGMENTED_PROMPT_VERSION,
    CutoverPlanRequest,
    FullPoolSegmentedCutoverOperator,
    LiveLanePool,
    LocalOperatorFilesystem,
    ProcessSnapshot,
    SystemProcessController,
    _QualificationRecorder,
    _validate_live_provider_contract,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
PREFIX = FIXTURES / "full_pool_segmented_v1_prefix"
UNKNOWN_PREFIX = FIXTURES / "full_pool_segmented_v1_prefix_unknown"


class FakeProcessController:
    def __init__(self, *, pid: int, command: str, cwd: Path, lock_path: Path) -> None:
        self.pid = pid
        self.command = command
        self.cwd = cwd
        self.lock_path = lock_path
        self.alive = True
        self.locked = True
        self.sleeps: list[float] = []

    def snapshot(self, pid: int) -> ProcessSnapshot | None:
        if not self.alive or pid != self.pid:
            return None
        return ProcessSnapshot(pid=pid, command=self.command, cwd=self.cwd)

    def lock_owner_pids(self, path: Path) -> tuple[int, ...]:
        if self.locked and path == self.lock_path:
            return (self.pid,)
        return ()

    def lock_is_released(self, path: Path) -> bool:
        return not self.locked and path == self.lock_path

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class FixtureFilesystem(LocalOperatorFilesystem):
    def __init__(self, reported_hashes: dict[Path, str]) -> None:
        self.reported_hashes = {path.resolve(): digest for path, digest in reported_hashes.items()}

    def sha256_file(self, path: Path) -> str:
        reported = self.reported_hashes.get(path.resolve())
        return reported if reported is not None else super().sha256_file(path)


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _setup(
    tmp_path: Path,
    *,
    fixture: Path = PREFIX,
) -> tuple[FullPoolSegmentedCutoverOperator, FakeProcessController, CutoverPlanRequest, Path, Path]:
    prefix = tmp_path / "v1-operational"
    shutil.copytree(fixture, prefix)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "users.csv").write_text("fixture\n", encoding="utf-8")
    (dataset / "videos.csv").write_text("fixture\n", encoding="utf-8")
    identity = _json(prefix / "concurrent_message_execution_run_identity.json")
    fingerprints = identity["sample_data_fingerprints"]
    assert isinstance(fingerprints, dict)
    dataset_hashes = fingerprints["dataset_files"]
    assert isinstance(dataset_hashes, dict)
    reported = {dataset / name: str(digest) for name, digest in dataset_hashes.items()}
    for name in dataset_hashes:
        path = dataset / name
        if not path.exists():
            path.write_text("fixture\n", encoding="utf-8")

    pid = 424242
    pidfile = tmp_path / "formal.pid"
    pidfile.write_text(f"{pid}\n", encoding="utf-8")
    lock_path = prefix / "concurrent_message_execution.lock"
    controller = FakeProcessController(
        pid=pid,
        command="python scripts/frozen-v1-operator.py run",
        cwd=tmp_path,
        lock_path=lock_path,
    )
    filesystem = FixtureFilesystem(reported)
    operator = FullPoolSegmentedCutoverOperator(process_controller=controller, filesystem=filesystem)
    formal_identity = _json(prefix / "full_pool_execution_identity.json")
    plan_path = tmp_path / "operator" / "plan.json"
    request = CutoverPlanRequest(
        prefix_workspace=prefix,
        frozen_prefix_workspace=tmp_path / "frozen-prefix",
        frozen_prefix_staging=tmp_path / ".frozen-prefix.staging",
        continuation_workspace=tmp_path / "continuation-v2",
        dataset_dir=dataset,
        pidfile=pidfile,
        expected_pid=pid,
        expected_command=controller.command,
        expected_cwd=tmp_path,
        expected_v1_output_identity=str(formal_identity["output_identity"]),
        expected_v1_operational_root=str(formal_identity["operational_root"]),
        expected_v1_source_root=str(formal_identity["source_root"]),
        expected_v1_candidate_root=str(formal_identity["candidate_root"]),
        expected_v1_recorded_runtime_workspace=str(identity["operational_workspace"]),
        expected_v1_recorded_output_target=str(identity["output_target"]),
        expected_v1_dataset_dir=str(fingerprints["dataset_dir"]),
        expected_v1_run_identity_hash=str(identity["identity_hash"]),
        expected_execution_contract_sha256=str(formal_identity["execution_contract_sha256"]),
        implementation_commit=SEGMENTED_IMPLEMENTATION_COMMIT,
        dataset_hashes={str(name): str(digest) for name, digest in dataset_hashes.items()},
        continuation_id="ticket-205-segmented-continuation-v2",
        authorization_reference=SEGMENTED_AUTHORIZATION_REFERENCE,
        preflight_artifact=tmp_path / "operator" / "preflight.json",
        cutover_artifact=tmp_path / "operator" / "cutover.json",
        reconciliation_artifact=tmp_path / "operator" / "reconciliation.json",
        continuation_authorization_artifact=tmp_path / "operator" / "continuation-authorization.json",
        qualification_artifact=tmp_path / "operator" / "qualification.json",
        stability_interval_seconds=0.01,
        stop_wait_timeout_seconds=1.0,
    )
    return operator, controller, request, plan_path, prefix


def test_system_lock_probe_never_creates_a_missing_lock(tmp_path: Path) -> None:
    missing = tmp_path / "missing.lock"
    with pytest.raises(RuntimeError, match="existing regular file"):
        SystemProcessController().lock_is_released(missing)
    assert not missing.exists()


def test_tail_acceptance_discards_a_valid_but_unterminated_final_record(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    records: list[dict[str, object]] = []
    previous: str | None = None
    for sequence in (1, 2):
        body: dict[str, object] = {
            "schema_version": "fixture-v1",
            "sequence": sequence,
            "previous_checksum": previous,
            "identity": "a" * 64,
        }
        checksum = hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        records.append({**body, "checksum": checksum})
        previous = checksum
    first = json.dumps(records[0], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    second = json.dumps(records[1], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.write_text(first + second, encoding="utf-8")

    accepted = FullPoolSegmentedCutoverOperator()._truncate_incomplete_jsonl_tail(
        path,
        expected_schema="fixture-v1",
        identity_field="identity",
        identity_value="a" * 64,
    )

    assert path.read_text(encoding="utf-8") == first
    assert accepted["accepted_bytes"] == len(first.encode())
    assert accepted["truncated_bytes"] == len(second.encode())


def test_prepare_and_dry_run_require_exact_process_lock_and_confirmation_token(tmp_path: Path) -> None:
    operator, controller, request, plan_path, _prefix = _setup(tmp_path)

    plan = operator.prepare(plan_path, request)
    preflight = operator.dry_run(plan_path)

    assert plan["implementation_commit"] == SEGMENTED_IMPLEMENTATION_COMMIT
    implementation_artifacts = plan["implementation_artifacts"]
    assert isinstance(implementation_artifacts, dict)
    assert set(implementation_artifacts) == {"operator_module", "continuation_module", "operator_cli"}
    assert preflight["manual_stop_required"] is True
    token = str(preflight["exact_confirmation_token"])
    assert token.startswith("CUTOVER-ISSUE-205-424242-")
    assert controller.sleeps == []

    controller.command = "crossed-reused-pid"
    assert operator.status(plan_path)["process_state"] == "pid_reused_or_crossed"
    controller.command = request.expected_command
    controller.alive = False
    controller.locked = False
    with pytest.raises(ValueError, match="exact high-risk confirmation token"):
        operator.cutover(plan_path, confirmation_token=token + "-wrong")


def _stop_and_cut_over(
    operator: FullPoolSegmentedCutoverOperator,
    controller: FakeProcessController,
    request: CutoverPlanRequest,
    plan_path: Path,
) -> dict[str, object]:
    operator.prepare(plan_path, request)
    preflight = operator.dry_run(plan_path)
    controller.alive = False
    controller.locked = False
    return operator.cutover(
        plan_path,
        confirmation_token=str(preflight["exact_confirmation_token"]),
    )


def _artifact_payload(path: Path) -> dict[str, object]:
    envelope = _json(path)
    payload = envelope["payload"]
    assert isinstance(payload, dict)
    return payload


def test_cutover_copies_raw_bytes_truncates_only_partial_tail_and_imports_runtime_terminal(
    tmp_path: Path,
) -> None:
    operator, controller, request, plan_path, prefix = _setup(tmp_path)
    attempt_path = prefix / "full_pool_attempt_ledger.jsonl"
    records = attempt_path.read_text(encoding="utf-8").splitlines()
    # Keep u2's reservation, but simulate termination between the runtime terminal and
    # the attempt-ledger physical/terminal close. The final bytes are incomplete only.
    attempt_path.write_bytes(("\n".join(records[:-2]) + "\n" + '{"schema_version":').encode())
    original = {path.relative_to(prefix).as_posix(): path.read_bytes() for path in prefix.rglob("*") if path.is_file()}

    authorization = _stop_and_cut_over(operator, controller, request, plan_path)

    frozen = request.frozen_prefix_workspace
    assert {path.relative_to(prefix).as_posix(): path.read_bytes() for path in prefix.rglob("*") if path.is_file()} == original
    assert not (frozen / "full_pool_attempt_ledger.jsonl").read_bytes().endswith(b'{"schema_version":')
    reconciliation = _artifact_payload(request.reconciliation_artifact)
    assert reconciliation["imported_terminal_count"] == 1
    imports = reconciliation["imports"]
    assert isinstance(imports, list) and imports[0]["pair_id"] == "u2:message_1:1"
    assert authorization["prefix_logical_count"] == 3
    assert authorization["prefix_physical_attempt_count"] == 3
    assert authorization["remaining_logical_cap"] == 109_197
    assert authorization["remaining_physical_cap"] == 120_117
    cutover = _artifact_payload(request.cutover_artifact)
    tails = cutover["jsonl_tail_acceptance"]
    assert isinstance(tails, list)
    ledger_tail = next(row for row in tails if row["relative_path"] == "full_pool_attempt_ledger.jsonl")
    assert ledger_tail["truncated_bytes"] > 0
    assert cutover["operator_sent_signals"] is False


def test_cutover_accepts_at_most_one_unknown_and_charges_full_three_attempt_window(tmp_path: Path) -> None:
    operator, controller, request, plan_path, _prefix = _setup(tmp_path, fixture=UNKNOWN_PREFIX)

    authorization = _stop_and_cut_over(operator, controller, request, plan_path)

    assert authorization["migration_unknown_pair_ids"] == ["u3:message_1:1"]
    assert authorization["migration_unknown_physical_charge"] == 3
    assert authorization["prefix_logical_count"] == 3
    assert authorization["prefix_physical_attempt_count"] == 3
    assert authorization["remaining_physical_cap"] == 120_114
    reconciliation = _artifact_payload(request.reconciliation_artifact)
    assert reconciliation["unknown_count"] == 1
    assert reconciliation["terminal_replay_count"] == 0


def test_cutover_rejects_two_runtime_unknowns_before_any_provider_boundary(tmp_path: Path) -> None:
    operator, controller, request, plan_path, prefix = _setup(tmp_path, fixture=UNKNOWN_PREFIX)
    journal_path = prefix / "concurrent_message_execution_journal.jsonl"
    records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    active_snapshot = next(record for record in reversed(records) if record["record_type"] == "snapshot")
    body = {
        "schema_version": "concurrent-message-execution-journal-v1",
        "sequence": len(records) + 1,
        "previous_checksum": records[-1]["checksum"],
        "run_id": records[-1]["run_id"],
        "identity_hash": request.expected_v1_run_identity_hash,
        "record_type": "event",
        "event_type": "variant_started",
        "event_identity": {
            "decision_variant": "primary",
            "event_type": "variant_started",
            "pair_id": "u4:message_1:1",
            "time_step": 1,
        },
        "batch_snapshot_hash": active_snapshot["snapshot_hash"],
        "payload": {
            "pair_id": "u4:message_1:1",
            "pair_schedule_position": 4,
            "message_id": "message_1",
            "message_title": "Offline continuation fixture",
            "user_id": "u4",
        },
    }
    checksum = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**body, "checksum": checksum}, sort_keys=True, separators=(",", ":")) + "\n")

    operator.prepare(plan_path, request)
    preflight = operator.dry_run(plan_path)
    controller.alive = False
    controller.locked = False
    with pytest.raises(ValueError, match="more than one migration unknown"):
        operator.cutover(plan_path, confirmation_token=str(preflight["exact_confirmation_token"]))

    assert not request.continuation_workspace.exists()
    assert not request.continuation_authorization_artifact.exists()


def test_status_is_read_only_and_reports_prefix_suffix_physical_unknown_and_source_state(
    tmp_path: Path,
) -> None:
    operator, controller, request, plan_path, _prefix = _setup(tmp_path, fixture=UNKNOWN_PREFIX)
    _stop_and_cut_over(operator, controller, request, plan_path)
    tracked_before = {
        path: path.read_bytes()
        for path in (
            plan_path,
            request.preflight_artifact,
            request.cutover_artifact,
            request.reconciliation_artifact,
            request.continuation_authorization_artifact,
        )
    }

    status = operator.status(plan_path)

    assert status == {
        "schema_version": "full-pool-segmented-operator-status-v1",
        "pid": request.expected_pid,
        "process_state": "not_running",
        "prefix_logical_count": 3,
        "suffix_logical_count": 0,
        "physical_attempt_count": 3,
        "unknown_pair_ids": ["u3:message_1:1"],
        "source_status": "frozen_prefix",
        "remaining_logical_cap": 109_197,
        "remaining_physical_cap": 120_114,
        "production_deploy_eligible": False,
    }
    assert {path: path.read_bytes() for path in tracked_before} == tracked_before


def test_status_replays_a_read_only_inflight_suffix_ledger_without_waiting_for_final_status(
    tmp_path: Path,
) -> None:
    operator, controller, request, plan_path, _prefix = _setup(tmp_path, fixture=UNKNOWN_PREFIX)
    _stop_and_cut_over(operator, controller, request, plan_path)
    continuation = request.continuation_workspace
    continuation.mkdir()
    identity_hash = "d" * 64
    (continuation / "segmented_continuation_identity.json").write_text(
        json.dumps({"identity_hash": identity_hash}, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    ledger_path = continuation / "segmented_continuation_ledger.jsonl"
    records: list[dict[str, object]] = []

    def append(event_type: str, payload: dict[str, object]) -> None:
        body: dict[str, object] = {
            "schema_version": "full-pool-segmented-continuation-ledger-v1",
            "sequence": len(records) + 1,
            "previous_checksum": records[-1]["checksum"] if records else None,
            "continuation_identity_hash": identity_hash,
            "event_type": event_type,
            "payload": payload,
        }
        checksum = hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        records.append({**body, "checksum": checksum})

    pair_ids = ["u3:message_1:1", "u4:message_1:1"]
    append("continuation_started", {"continuation_id": request.continuation_id})
    append(
        "suffix_wave_reserved",
        {
            "pair_ids": pair_ids,
            "physical_reservation": 6,
            "maximum_attempts_per_dispatch": 3,
        },
    )
    for lane_id, pair_id in enumerate(pair_ids):
        append("pair_dispatched", {"pair_id": pair_id, "lane_id": lane_id})
    ledger_path.write_bytes(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in records).encode()
        + b'{"schema_version":'
    )
    ledger_before = ledger_path.read_bytes()

    status = operator.status(plan_path)

    assert status["suffix_logical_count"] == 2
    assert status["physical_attempt_count"] == 6
    assert status["unknown_pair_ids"] == pair_ids
    assert status["source_status"] == "concurrent_suffix_running"
    assert status["remaining_logical_cap"] == 109_195
    assert status["remaining_physical_cap"] == 120_114
    assert ledger_path.read_bytes() == ledger_before


def test_qualification_artifact_binds_authorization_and_exact_ten_lane_wave(tmp_path: Path) -> None:
    _operator, _controller, request, _plan_path, _prefix = _setup(tmp_path)
    authorization_hash = "b" * 64
    recorder = _QualificationRecorder(
        path=request.qualification_artifact,
        filesystem=LocalOperatorFilesystem(),
        continuation_authorization_sha256=authorization_hash,
    )
    recorder.observe(
        SegmentedQualificationWave(
            pair_ids=tuple(f"u{index}:message_1:2" for index in range(10)),
            elapsed_seconds=2.0,
            physical_attempt_count=10,
            provider_response_count=10,
            successful_decision_count=10,
            terminal_status_counts={"succeeded": 10},
            observed_model_counts={"gpt-5.6-sol": 10},
            usage_complete_response_count=10,
            usage_missing_response_count=0,
            usage_malformed_response_count=0,
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            cached_input_tokens=0,
        )
    )

    FullPoolSegmentedCutoverOperator()._validate_qualification_state(
        request,
        continuation_exists=True,
        authorization_hash=authorization_hash,
    )
    with pytest.raises(ValueError, match="failed or crossed"):
        FullPoolSegmentedCutoverOperator()._validate_qualification_state(
            request,
            continuation_exists=True,
            authorization_hash="c" * 64,
        )


class _FakePiClient:
    external_provider_client = True
    safe_metadata = {
        "provider_transport": "openai-codex",
        "adapter_identity": "openai-codex-subscription-client-v1",
        "authentication": "local_oauth_subscription",
        "requested_model_aliases": {
            "gpt-5.4-mini": "gpt-5.4-mini",
            "gpt-5.4-2026-03-05": "gpt-5.4",
            "gpt-5.5-2026-04-23": "gpt-5.5",
            "gpt-5.6-sol": "gpt-5.6-sol",
        },
        "output_token_ceiling_enforcement": "application_fail_closed",
    }

    def __init__(self, *, response_timeout_seconds: float) -> None:
        self.response_timeout_seconds = response_timeout_seconds
        self.ready = True
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_live_lane_pool_builds_exactly_ten_isolated_clients_and_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    monkeypatch.setenv("LLM_ABM_RUN_FULL_POOL_SEGMENTED_CONTINUATION", "1")
    clients: list[_FakePiClient] = []

    def client_factory(**kwargs: object) -> _FakePiClient:
        timeout = kwargs["response_timeout_seconds"]
        assert isinstance(timeout, (int, float)) and not isinstance(timeout, bool)
        client = _FakePiClient(response_timeout_seconds=float(timeout))
        clients.append(client)
        return client

    pool = LiveLanePool(prompt_version=SEGMENTED_PROMPT_VERSION, client_factory=client_factory)  # type: ignore[arg-type]
    adapters = [pool.adapter_factory(lane_id) for lane_id in range(10)]

    assert len(adapters) == 10
    assert len({id(adapter) for adapter in adapters}) == 10
    assert len({id(client) for client in clients}) == 10
    assert all(adapter.__dict__["client"] is clients[index] for index, adapter in enumerate(adapters))
    metadata = adapters[0].safe_metadata  # type: ignore[attr-defined]
    _validate_live_provider_contract(metadata)
    assert metadata["prompt_version"] == "jinjiang-concurrent-message-primary-prompt-v1"
    crossed = dict(metadata)
    crossed["prompt_version"] = "concurrent-primary-observed-v2"
    with pytest.raises(ValueError, match="prompt_version"):
        _validate_live_provider_contract(crossed)
    with pytest.raises(ValueError, match="duplicate lane"):
        pool.adapter_factory(9)
    with pytest.raises(ValueError, match="outside"):
        pool.adapter_factory(10)
    pool.close()
    assert all(client.closed for client in clients)
