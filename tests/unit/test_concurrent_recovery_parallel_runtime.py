"""Offline worker/resource tests, with no external requests."""

from types import SimpleNamespace

import pytest

from llm_abm_sim import concurrent_robustness_operator as operator
from llm_abm_sim import concurrent_robustness_v2 as v2
from tests.unit.test_concurrent_recovery_parallel_progress import MODEL, proposal
from tests.unit.test_concurrent_robustness_operator import _Transport


def test_four_clients_are_independent_and_close_without_any_probe(monkeypatch):
    clients = []

    def client(model, timeout):
        assert model == MODEL
        value = _Transport("gemini", {})
        clients.append(value)
        return value

    monkeypatch.setattr(operator, "_new_client", client)
    cells = tuple(v2._PromptModelCell.model_validate(row) for row in proposal()["frozen_context"]["prompt_model_cells"])
    manifest = SimpleNamespace(prompt_model_cells=cells, execution_profile="formal")
    with operator._task_model_resources(manifest, 30, MODEL, maximum_inflight=4) as fresh:
        adapters = fresh()
        assert len(adapters) == 4 and len(clients) == 4
        assert all(len(pool.lanes) == 4 for pool in adapters.values())
        assert len({id(lane) for pool in adapters.values() for lane in pool.lanes}) == 16
        assert len({id(lane.client) for lane in next(iter(adapters.values())).lanes}) == 4
        assert all(not c.calls for c in clients)
    assert all(c.closed == 1 for c in clients)


def test_study_batch_scheduler_runs_four_requests_and_reuses_persisted_results(tmp_path, monkeypatch):
    import threading
    import time

    from llm_abm_sim import _concurrent_recovery_parallel_runtime as runtime
    from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, recovery_scope
    from llm_abm_sim._concurrent_recovery_progress import CampaignProgress
    from llm_abm_sim.concurrent_message_experiment import _VariantDecisionContext
    from tests.unit.test_concurrent_recovery_parallel_progress import batch, start
    from tests.unit.test_concurrent_recovery_progress import _journal
    from tests.unit.test_robustness_provider_adapters import _context

    mutex = threading.Lock()
    barrier = threading.Barrier(4)
    counters = {"active": 0, "peak": 0, "entered": 0}

    class Transport(_Transport):
        def create_response(self, *args, **kwargs):
            with mutex:
                counters["active"] += 1
                counters["entered"] += 1
                number = counters["entered"]
                counters["peak"] = max(counters["peak"], counters["active"])
            try:
                if number <= 4:
                    barrier.wait(timeout=5)
                time.sleep(0.005)
                return super().create_response(*args, **kwargs)
            finally:
                with mutex:
                    counters["active"] -= 1

    cells = tuple(v2._PromptModelCell.model_validate(row) for row in proposal()["frozen_context"]["prompt_model_cells"])
    clients = [Transport("gemini", {}) for _ in range(4)]
    pool = runtime.ParallelAdapterPool(tuple(operator._adapter_for_cell(cells[4], c) for c in clients))
    data = _context()
    context = _VariantDecisionContext(
        decision_variant="primary",
        prompt_token=cells[4].prompt_version,
        **{k: data[k] for k in ("post", "profile", "peer_context", "platform_context")},
    )
    work = tuple(runtime.FrozenWork(row["coordinates"], context) for row in batch()["pairs"])
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, _ = start(journal, reserve=False)
        writers = []
        original = CampaignJournal.append

        def observed(self, kind, payload):
            writers.append(threading.get_ident())
            return original(self, kind, payload)

        monkeypatch.setattr(CampaignJournal, "append", observed)
        runtime.run_frozen_batch(
            state=state, journal=journal, pool=pool, work=work, check_dispatch_window=lambda: None, backoff_seconds=0.01
        )
        assert counters["peak"] == 4 and counters["entered"] == 60
        assert set(writers) == {threading.get_ident()}
        assert len(state.success_decisions) == 60 and state.physical_attempts == 60
        assert not state.has_inflight and not state.judgments
        reread = CampaignProgress.replay(proposal(), CampaignJournal.read(identity))
        runtime.run_frozen_batch(
            state=reread,
            journal=journal,
            pool=pool,
            work=work,
            check_dispatch_window=lambda: None,
            backoff_seconds=0.01,
        )
        assert counters["entered"] == 60 and reread.physical_attempts == 60


@pytest.mark.parametrize("failure", ["quota", "unknown", "window"])
def test_first_stop_drains_dispatched_requests_without_replacement(tmp_path, failure):
    import threading
    import time

    from llm_abm_sim import _concurrent_recovery_parallel_runtime as runtime
    from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
    from llm_abm_sim.concurrent_message_experiment import _VariantDecisionContext
    from llm_abm_sim.decision import ProviderResponseProvenanceUnknown
    from llm_abm_sim.providers.robustness import ProviderAttemptFailure
    from tests.unit.test_concurrent_recovery_parallel_progress import batch, start
    from tests.unit.test_concurrent_recovery_progress import _journal
    from tests.unit.test_robustness_provider_adapters import _context

    mutex = threading.Lock()
    barrier = threading.Barrier(4)
    count = 0

    class Transport(_Transport):
        def create_response(self, *args, **kwargs):
            nonlocal count
            with mutex:
                count += 1
                number = count
            if number <= 4:
                barrier.wait(timeout=5)
            if number == 1 and failure == "quota":
                raise ProviderAttemptFailure(category="quota_exhausted", retryable=False)
            if number == 1 and failure == "unknown":
                raise ProviderResponseProvenanceUnknown("offline unknown")
            time.sleep(0.01 * number)
            return super().create_response(*args, **kwargs)

    cell = v2._PromptModelCell.model_validate(proposal()["frozen_context"]["prompt_model_cells"][4])
    pool = runtime.ParallelAdapterPool(
        tuple(operator._adapter_for_cell(cell, Transport("gemini", {})) for _ in range(4))
    )
    data = _context()
    context = _VariantDecisionContext(
        decision_variant="primary",
        prompt_token=cell.prompt_version,
        **{k: data[k] for k in ("post", "profile", "peer_context", "platform_context")},
    )
    work = tuple(runtime.FrozenWork(row["coordinates"], context) for row in batch()["pairs"])
    checks = 0

    def check():
        nonlocal checks
        checks += 1
        if failure == "window" and checks == 5:
            raise RuntimeError("offline window ended")

    with recovery_scope(_journal(tmp_path)):
        journal = CampaignJournal.open(_journal(tmp_path))
        state, _ = start(journal, reserve=False)
        with pytest.raises((RecoveryCampaignError, v2._V2CellStopped, RuntimeError)):
            runtime.run_frozen_batch(
                state=state, journal=journal, pool=pool, work=work, check_dispatch_window=check, backoff_seconds=0.01
            )
        assert count == state.physical_attempts == 4
        assert len(state.success_decisions) == (4 if failure == "window" else 3)
        assert state.has_inflight == (failure == "unknown")
        assert state.status == {"quota": "stopped", "unknown": "reconciliation_required", "window": "running"}[failure]
