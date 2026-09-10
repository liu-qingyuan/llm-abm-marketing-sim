from copy import deepcopy
from typing import Any

import pytest

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from llm_abm_sim._concurrent_recovery_kimi_migration import terms
from tests.unit.test_concurrent_recovery_progress import _journal
from tests.unit.test_kimi_migration_terms import completed_gemini


def admitted(journal):
    state = completed_gemini(journal)
    grant = {'approval': {'path': '/fixture/migration.json', 'sha256': 'e' * 64},
             'destination_model': 'kimi-k3', 'maximum_inflight': 5,
             'output_token_ceiling': 1024, 'maximum_spend_cny': 100, 'terms': terms(state)}
    state.append(journal, 'kimi_official_migration_accepted', grant)
    return state


def test_activation_restores_only_original_batch_and_preserves_attempts(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = admitted(journal)
        assert state.kimi_migration_approval is not None
        attempts = deepcopy(state.new_attempts)
        physical = state.physical_attempts
        state.append(journal, 'kimi_official_execution_activated', {'approval': state.kimi_migration_approval['approval']})
        assert state.current_model == 'kimi-coding/k3-256k'
        assert state.status == 'ready' and not state.model_stage_complete
        assert state.parallel_active_batch == (12, 0)
        assert state.effective_parallel_approval is not None
        assert state.effective_parallel_approval['maximum_inflight'] == 5
        assert state.new_attempts == attempts and state.physical_attempts == physical
        check = state.effective_self_check(state.current_model)
        assert check is not None and check['qualification_kind'] == 'accepted_official_migration'


def running(journal):
    state = admitted(journal)
    assert state.kimi_migration_approval is not None
    state.append(journal, 'kimi_official_execution_activated', {'approval': state.kimi_migration_approval['approval']})
    state.append(journal, 'epoch_admitted', {'ordinal': len(state.epochs) + 1, 'requested_model': state.current_model,
                 'epoch_identity_sha256': 'f' * 64, 'plan_path': '/fixture/official-epoch.json', 'plan_sha256': 'f' * 64})
    return state


def test_official_attempt_keeps_prior_403_and_rejects_success_resend(tmp_path):
    import pytest

    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError
    from tests.unit.test_kimi_migration_judgment import official_payload

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = running(journal)
        old = deepcopy(state.new_attempts[12, 0][0])
        state.append(journal, 'parallel_attempt_intent', {'cell_index': 12, 'pair_schedule_position': 0, 'attempt_number': 2})
        p = official_payload(True)
        state.append(journal, 'parallel_attempt_settled', {'cell_index': 12, 'pair_schedule_position': 0,
                     'attempt': p['new_attempts'][-1], 'decision': p['decision']})
        assert state.new_attempts[12, 0][0] == old
        assert state.new_attempts[12, 0][-1].observed_model_counts == {'kimi-k3': 1}
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'parallel_attempt_intent', {'cell_index': 12, 'pair_schedule_position': 0, 'attempt_number': 3})


def test_persisted_official_judgment_binds_migration_not_old_output_amendment(tmp_path):
    from tests.unit.test_concurrent_recovery_judgment import _rehash
    from tests.unit.test_kimi_migration_judgment import official_payload

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = running(journal)
        assert state.kimi_migration_approval is not None
        p = official_payload(True)
        state.append(journal, 'parallel_attempt_intent', {'cell_index': 12, 'pair_schedule_position': 0, 'attempt_number': 2})
        state.append(journal, 'parallel_attempt_settled', {'cell_index': 12, 'pair_schedule_position': 0,
                     'attempt': p['new_attempts'][-1], 'decision': p['decision']})
        coords = state.parallel_batches[12, 0]['pairs'][0]['coordinates']
        state.append(journal, 'pair_reserved', coords)
        p.update(cell=state.cells[12].model_dump(mode='json'),
                 pair={k: v for k, v in coords.items() if k != 'cell_index'},
                 new_attempts=[a.model_dump(mode='json') for a in state.new_attempts[12, 0]],
                 epoch_identity_sha256='f' * 64, official_migration_approval=state.kimi_migration_approval['approval'])
        _rehash(p)
        import pytest

        from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError
        wrong = deepcopy(p)
        wrong['official_migration_approval'] = {'path': '/wrong/approval.json', 'sha256': '1' * 64}
        _rehash(wrong)
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'judgment_persisted', {'judgment': wrong})
        state.append(journal, 'judgment_persisted', {'judgment': p})
        assert state.pending_judgment is not None
        assert state.pending_judgment['schema_version'] == 'concurrent-recovery-provider-judgment-v4'


def test_cash_guard_counts_every_inflight_and_never_fills_historical_usage(tmp_path):
    import pytest

    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError
    from llm_abm_sim._concurrent_recovery_kimi_migration import cash_budget

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = running(journal)
        old = deepcopy(state.new_attempts[12, 0])
        for position in range(4):
            state.append(journal, 'parallel_attempt_intent', {'cell_index': 12, 'pair_schedule_position': position,
                         'attempt_number': 2 if position == 0 else 1})
        fact = cash_budget(state)
        assert fact['reserved_micro_cny'] == 4 * 21073920
        assert fact['can_reserve_one'] is False
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'parallel_attempt_intent', {'cell_index': 12, 'pair_schedule_position': 4, 'attempt_number': 1})
        assert state.new_attempts[12, 0] == old
        assert state.new_attempts[12, 0][0].total_usage is None


def test_official_pool_preflight_checks_independent_five_clients_and_prompt(tmp_path):
    from types import SimpleNamespace

    import pytest

    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError
    from llm_abm_sim._concurrent_recovery_kimi_migration import preflight
    from llm_abm_sim._concurrent_recovery_parallel_runtime import ParallelAdapterPool
    from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter
    from tests.unit.test_moonshot_official_adapter import Client

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        state = admitted(CampaignJournal.open(identity))
        clients: list[Any] = [Client() for _ in range(5)]
        for client in clients:
            client.external_provider_client = True
            client.output_token_ceiling_enforcement = 'wire_only'
        cells = tuple(c for c in state.cells if c.requested_model == 'kimi-coding/k3-256k')
        manifest: Any = SimpleNamespace(prompt_model_cells=state.cells, execution_profile='formal')
        pools: Any = {c.cell_id: ParallelAdapterPool(tuple(OfficialKimiDecisionAdapter(prompt_version=c.prompt_version, client=x)
                 for x in clients)) for c in cells}
        # Fixture cell hashes are symbolic. Match the actual registered prompt hash.
        manifest.prompt_model_cells = tuple(c.model_copy(update={'prompt_canonical_hash': pools[c.cell_id].lanes[0].request_evidence['prompt_canonical_hash']})
                                           if c in cells else c for c in state.cells)
        preflight(state, manifest, pools)
        bad = dict(pools)
        bad[cells[0].cell_id] = ParallelAdapterPool(pools[cells[0].cell_id].lanes[:4])
        with pytest.raises(RecoveryCampaignError):
            preflight(state, manifest, bad)
        assert all(not c.calls for c in clients)


def test_official_batch_parallel_drain_and_duplicate_zero_resend(tmp_path, monkeypatch):
    import threading
    import time

    from llm_abm_sim import _concurrent_recovery_parallel_runtime as runtime
    from llm_abm_sim.concurrent_message_experiment import _VariantDecisionContext
    from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter
    from tests.unit.test_moonshot_official_adapter import Client
    from tests.unit.test_robustness_provider_adapters import _context

    mutex = threading.Lock()
    barrier = threading.Barrier(4)
    counters = {'active': 0, 'peak': 0, 'calls': 0}
    class Transport(Client):
        def create_response(self, *args, **kwargs):
            with mutex:
                counters['active'] += 1
                counters['calls'] += 1
                number = counters['calls']
                counters['peak'] = max(counters['peak'], counters['active'])
            try:
                if number <= 4:
                    barrier.wait(timeout=5)
                time.sleep(.002)
                return super().create_response(*args, **kwargs)
            finally:
                with mutex:
                    counters['active'] -= 1
    clients: list[Any] = [Transport() for _ in range(5)]
    for c in clients:
        c.external_provider_client = True
        c.output_token_ceiling_enforcement = 'wire_only'
    monkeypatch.setattr(runtime, '_OFFICIAL_DISPATCH_INTERVAL_SECONDS', 0)
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = running(journal)
        cell = state.cells[12]
        data = _context()
        context = _VariantDecisionContext(decision_variant='primary', prompt_token=cell.prompt_version,
                  **{k: data[k] for k in ('post', 'profile', 'peer_context', 'platform_context')})
        work = tuple(runtime.FrozenWork(row['coordinates'], context) for row in state.parallel_batches[12, 0]['pairs'])
        # The fixture's original frozen inputs must agree with this actual context.
        state.parallel_batches[12, 0]['pairs'] = [w.reservation() for w in work]
        pool = runtime.ParallelAdapterPool(tuple(OfficialKimiDecisionAdapter(prompt_version=cell.prompt_version, client=c) for c in clients))
        before = state.physical_attempts
        runtime.run_frozen_batch(state=state, journal=journal, pool=pool, work=work,
                                 check_dispatch_window=lambda: None, backoff_seconds=0)
        assert counters['calls'] == 60 and counters['peak'] == 4
        assert state.physical_attempts == before + 60
        assert len([k for k in state.success_decisions if k[0] == 12]) == 60
        runtime.run_frozen_batch(state=state, journal=journal, pool=pool, work=work,
                                 check_dispatch_window=lambda: None, backoff_seconds=0)
        assert counters['calls'] == 60
        assert not state.has_inflight


@pytest.mark.parametrize('failure', ['quota', 'unknown', 'evidence_rejected'])
def test_official_new_hard_stop_drains_and_never_retries(tmp_path, monkeypatch, failure):
    import threading

    from llm_abm_sim import _concurrent_recovery_parallel_runtime as runtime
    from llm_abm_sim.concurrent_message_experiment import _VariantDecisionContext
    from llm_abm_sim.decision import ProviderAttemptFailure, ProviderResponseProvenanceUnknown
    from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter
    from tests.unit.test_moonshot_official_adapter import Client
    from tests.unit.test_robustness_provider_adapters import _context

    barrier = threading.Barrier(4)
    entered = []
    class Transport(Client):
        def create_response(self, *args, **kwargs):
            entered.append(self)
            first = len(entered) == 1
            barrier.wait(timeout=5)
            if first:
                if failure == 'quota':
                    raise ProviderAttemptFailure(category='quota_exhausted', retryable=False, status_code=429)
                if failure == 'unknown':
                    raise ProviderResponseProvenanceUnknown('fixture unknown')
            return super().create_response(*args, **kwargs)
    clients: list[Any] = [Transport() for _ in range(5)]
    for c in clients:
        c.external_provider_client = True
        c.output_token_ceiling_enforcement = 'wire_only'
    monkeypatch.setattr(runtime, '_OFFICIAL_DISPATCH_INTERVAL_SECONDS', 0)
    if failure == 'evidence_rejected':
        original = runtime.v2._v2_attempt_evidence
        rejected = False
        def broken_evidence(**kwargs):
            nonlocal rejected
            if not rejected:
                rejected = True
                raise ValueError('fixture accounting validation failure')
            return original(**kwargs)
        monkeypatch.setattr(runtime.v2, '_v2_attempt_evidence', broken_evidence)
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = running(journal)
        cell = state.cells[12]
        data = _context()
        context = _VariantDecisionContext(decision_variant='primary', prompt_token=cell.prompt_version,
                  **{k: data[k] for k in ('post', 'profile', 'peer_context', 'platform_context')})
        work = tuple(runtime.FrozenWork(row['coordinates'], context) for row in state.parallel_batches[12, 0]['pairs'])
        state.parallel_batches[12, 0]['pairs'] = [w.reservation() for w in work]
        pool = runtime.ParallelAdapterPool(tuple(OfficialKimiDecisionAdapter(prompt_version=cell.prompt_version, client=c) for c in clients))
        with pytest.raises((RecoveryCampaignError, runtime.v2._V2CellStopped)):
            runtime.run_frozen_batch(state=state, journal=journal, pool=pool, work=work,
                                     check_dispatch_window=lambda: None, backoff_seconds=0)
        assert len(entered) == 4
        assert state.status == ('stopped' if failure == 'quota' else 'reconciliation_required')
        assert state.has_inflight == (failure != 'quota')
        assert len([k for k in state.success_decisions if k[0] == 12]) == 3
        with pytest.raises((RecoveryCampaignError, runtime.v2._V2CellStopped)):
            runtime.run_frozen_batch(state=state, journal=journal, pool=pool, work=work,
                                     check_dispatch_window=lambda: None, backoff_seconds=0)
        assert len(entered) == 4


def test_public_operator_activates_after_preflight_and_terminal_rerun_opens_no_client(tmp_path, monkeypatch):
    from importlib import import_module
    from types import SimpleNamespace

    from llm_abm_sim import _concurrent_recovery_bundle as bundle
    from llm_abm_sim import concurrent_robustness_operator as operator
    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessStudy
    from llm_abm_sim.providers import moonshot
    from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter
    from tests.unit.test_moonshot_official_adapter import Client

    # Load import-time dependencies before replacing the publication seam.
    import_module('llm_abm_sim._concurrent_recovery_task_runtime')
    clients = []
    class Transport(Client):
        external_provider_client = True
        output_token_ceiling_enforcement = 'wire_only'
        def __init__(self, **_kwargs):
            super().__init__()
            self.closed = False
            clients.append(self)
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            self.closed = True
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = admitted(journal)
    # Resource fixtures qualify real registered prompts; they do not generate Formal results.
    cells = tuple(c.model_copy(update={'prompt_canonical_hash': OfficialKimiDecisionAdapter(prompt_version=c.prompt_version,
                  client=Client()).request_evidence['prompt_canonical_hash']})
                  if c.requested_model == 'kimi-coding/k3-256k' else c for c in state.cells)
    manifest = SimpleNamespace(prompt_model_cells=cells, execution_profile='formal')
    context = SimpleNamespace(state=state, journal=journal, origins=SimpleNamespace(campaign=identity,
                              source=SimpleNamespace(manifest=manifest)))
    monkeypatch.setattr(task, '_context', lambda _path: context)
    monkeypatch.setattr(task, '_task_status', lambda _context: {'status': state.status, 'authorization_current': True})
    monkeypatch.setattr(moonshot, 'MoonshotOfficialClient', Transport)
    monkeypatch.setattr(bundle, 'publish_recovery_bundle', lambda _context: None)
    monkeypatch.setenv('LLM_ABM_RUN_LIVE_LLM', '1')
    def run(_study, _path, *, model_resources):
        assert state.kimi_migration_active and state.status == 'ready'
        with model_resources(state.current_model) as fresh:
            assert len(fresh()) == 4
        state.status = 'stopped'
        return {'status': 'stopped'}
    monkeypatch.setattr(ConcurrentRobustnessStudy, 'run_task', run)
    result = operator.run_concurrent_robustness_kimi_official('/fixture/task.json', api_key='test-not-secret')
    assert result['status'] == 'stopped'
    assert len(clients) == 5 and all(c.closed and not c.calls for c in clients)
    assert CampaignJournal.read(identity).records[-1]['kind'] == 'kimi_official_execution_activated'
    operator.run_concurrent_robustness_kimi_official('/fixture/task.json', api_key='')
    assert len(clients) == 5


def test_official_realization_retains_actual_model_identity():
    from llm_abm_sim._concurrent_recovery_judgment import RecoveryJudgmentV1
    from tests.unit.test_kimi_migration_judgment import official_payload

    judgment = RecoveryJudgmentV1.model_validate(official_payload())
    terminal = judgment.realized_projection(realization_source_identity='a' * 64)
    assert terminal.observed_model == 'kimi-k3'
