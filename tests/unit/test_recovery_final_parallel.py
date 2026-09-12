from copy import deepcopy

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, recovery_scope
from tests.unit.test_concurrent_recovery_progress import _journal
from tests.unit.test_recovery_final_model import completed, grant


def prepared(journal):
    s = completed(journal)
    s.append(journal, "final_model_continuation_accepted", grant())
    s.status = "paused"
    s.epochs.append({"requested_model": s.current_model})
    s.self_checks[s.current_model] = {"attempt": {"outcome": "succeeded"}}
    return s


def approval():
    return {
        "approval": {"path": "/fixture/parallel.json", "sha256": "d" * 64},
        "requested_model": "openai-codex/gpt-5.6-sol",
        "maximum_inflight": 5,
        "stop_after_model": True,
    }


def test_five_way_acceptance_retains_history_and_ignores_kimi_retry(tmp_path):
    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = prepared(journal)
        s.kimi_retry_policy = {"maximum_active_lanes": 2, "backoff_base_seconds": 99}
        before = deepcopy((s.prefix, s.physical_attempts, s.new_attempts, s.kimi_retry_policy))
        s.append(journal, "final_model_parallel_accepted", approval())
        assert s.effective_parallel_approval["maximum_inflight"] == 5
        assert s.effective_retry_policy is None
        assert before == (s.prefix, s.physical_attempts, s.new_attempts, s.kimi_retry_policy)
        assert s.status == "paused"


def test_public_parallel_admission_binds_receipt_and_repeats_without_append(tmp_path, monkeypatch):
    import hashlib
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from types import SimpleNamespace

    import pytest

    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError
    from llm_abm_sim._concurrent_recovery_final_model import validate_parallel_receipt

    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = prepared(journal)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ref = {"path": "/fixture/task.json", "sha256": "d" * 64}
    origins = SimpleNamespace(
        campaign=identity,
        handoff=SimpleNamespace(model_dump=lambda **_: ref),
        task_plan={"authorization": {"approved_at_utc": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}},
    )
    a = {
        "schema_version": "concurrent-recovery-final-model-parallel-approval-v1",
        "status": "approved",
        "authorization_reference": "user-cancel-flash-run-gpt",
        "approved_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task_plan": ref,
        "paused_head_sha256": journal.head,
        **{k: v for k, v in approval().items() if k != "approval"},
    }
    path = tmp_path / "approval.json"
    from llm_abm_sim.concurrent_robustness_formal_execution import _canonical_json_bytes

    path.write_bytes(_canonical_json_bytes(a))
    path.chmod(0o444)
    payload = {**approval(), "approval": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
    monkeypatch.setattr(task, "_current", lambda *_: True)
    with pytest.raises(RecoveryCampaignError):
        validate_parallel_receipt(origins, s, payload, now, "0" * 64)
    context = SimpleNamespace(origins=origins, state=s, journal=journal, plan={})
    monkeypatch.setattr(task, "_context", lambda _: context)
    monkeypatch.setattr(task, "_read_revocation", lambda _: None)
    args = {"approval_path": Path(payload["approval"]["path"]), "approval_sha256": payload["approval"]["sha256"]}
    first = task.accept_recovery_task_final_model_parallel("/fixture/task.json", **args)
    head = journal.head
    second = task.accept_recovery_task_final_model_parallel("/fixture/task.json", **args)
    assert first == second and head == journal.head and first["provider_calls"] == 0
    assert first["credential_reads"] == 0


def test_parallel_rejects_hard_stops_unknowns_partial_barriers_and_capacity(tmp_path):
    import pytest

    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError

    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        base = prepared(journal)
        for field, value in [
            ("status", "stopped"),
            ("task_revoked", True),
            ("inflight", {}),
            ("parallel_inflight", {(16, 0): 1}),
            ("reservation", {}),
            ("pending_judgment", {}),
            ("pending_realized", {}),
            ("physical_attempts", base.proposal["maximum_new_physical_attempts"]),
        ]:
            state = deepcopy(base)
            setattr(state, field, value)
            with pytest.raises(RecoveryCampaignError):
                state.append(journal, "final_model_parallel_accepted", approval())
        for n in (1, 60):
            state = deepcopy(base)
            state.prefix[16] = n
            with pytest.raises(RecoveryCampaignError):
                state.append(journal, "final_model_parallel_accepted", approval())
        for n in (1, 4, 6, True):
            a = approval()
            a["maximum_inflight"] = n
            with pytest.raises(RecoveryCampaignError):
                base.append(journal, "final_model_parallel_accepted", a)
        base.append(journal, "final_model_parallel_accepted", approval())
        with pytest.raises(RecoveryCampaignError):
            base.append(journal, "final_model_parallel_accepted", approval())


def test_original_gpt_resources_make_five_independent_clients_without_probe(monkeypatch):
    from types import SimpleNamespace

    from llm_abm_sim import concurrent_robustness_operator as operator
    from llm_abm_sim import concurrent_robustness_v2 as v2
    from tests.unit.test_concurrent_recovery_parallel_progress import proposal
    from tests.unit.test_concurrent_robustness_operator import _Transport

    clients = []

    def client(model, timeout):
        assert model == "openai-codex/gpt-5.6-sol"
        value = _Transport("openai", {})
        clients.append(value)
        return value

    monkeypatch.setattr(operator, "_new_client", client)
    cells = tuple(v2._PromptModelCell.model_validate(row) for row in proposal()["frozen_context"]["prompt_model_cells"])
    manifest = SimpleNamespace(prompt_model_cells=cells, execution_profile="formal")
    with operator._task_model_resources(manifest, 30, "openai-codex/gpt-5.6-sol", maximum_inflight=5) as fresh:
        adapters = fresh()
        assert len(clients) == 5 and all(len(p.lanes) == 5 for p in adapters.values())
        assert all(not c.calls for c in clients)
    assert all(c.closed == 1 for c in clients)


def test_study_batch_scheduler_runs_five_gpt_requests_and_reuses_persisted_results(tmp_path, monkeypatch):
    import threading
    import time

    from llm_abm_sim import _concurrent_recovery_parallel_runtime as runtime
    from llm_abm_sim import concurrent_robustness_operator as operator
    from llm_abm_sim import concurrent_robustness_v2 as v2
    from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, recovery_scope
    from llm_abm_sim.concurrent_message_experiment import _VariantDecisionContext
    from tests.unit.test_concurrent_recovery_parallel_progress import batch, proposal
    from tests.unit.test_concurrent_recovery_progress import _journal
    from tests.unit.test_concurrent_robustness_operator import _Transport
    from tests.unit.test_robustness_provider_adapters import _context

    mutex = threading.Lock()
    barrier = threading.Barrier(5)
    counters = {"active": 0, "peak": 0, "entered": 0}

    class Transport(_Transport):
        def create_response(self, *args, **kwargs):
            with mutex:
                counters["active"] += 1
                counters["entered"] += 1
                number = counters["entered"]
                counters["peak"] = max(counters["peak"], counters["active"])
            try:
                if number <= 5:
                    barrier.wait(timeout=5)
                time.sleep(0.005)
                return super().create_response(*args, **kwargs)
            finally:
                with mutex:
                    counters["active"] -= 1

    cells = tuple(v2._PromptModelCell.model_validate(row) for row in proposal()["frozen_context"]["prompt_model_cells"])
    clients = [Transport("openai", {}) for _ in range(5)]
    pool = runtime.ParallelAdapterPool(tuple(operator._adapter_for_cell(cells[16], c) for c in clients))
    data = _context()
    context = _VariantDecisionContext(
        decision_variant="primary",
        prompt_token=cells[16].prompt_version,
        **{k: data[k] for k in ("post", "profile", "peer_context", "platform_context")},
    )
    work = tuple(runtime.FrozenWork({**row["coordinates"], "cell_index": 16}, context) for row in batch()["pairs"])
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = prepared(journal)
        state.append(journal, "final_model_parallel_accepted", approval())
        state.status = "running"
        state.epochs[-1]["epoch_identity_sha256"] = "e" * 64
        base_physical = state.physical_attempts
        base_success = len(state.success_decisions)
        writers = []
        original = CampaignJournal.append

        def observed(self, kind, payload):
            writers.append(threading.get_ident())
            return original(self, kind, payload)

        monkeypatch.setattr(CampaignJournal, "append", observed)
        runtime.run_frozen_batch(
            state=state, journal=journal, pool=pool, work=work, check_dispatch_window=lambda: None, backoff_seconds=0.01
        )
        assert counters["peak"] == 5 and counters["entered"] == 60
        assert set(writers) == {threading.get_ident()}
        assert len(state.success_decisions) == base_success + 60 and state.physical_attempts == base_physical + 60
        assert not state.has_inflight
        reread = deepcopy(state)
        runtime.run_frozen_batch(
            state=reread,
            journal=journal,
            pool=pool,
            work=work,
            check_dispatch_window=lambda: None,
            backoff_seconds=0.01,
        )
        assert counters["entered"] == 60 and reread.physical_attempts == base_physical + 60
