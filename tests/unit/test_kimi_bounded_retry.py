import httpx
import pytest

from llm_abm_sim.decision import ProviderAttemptFailure
from llm_abm_sim.providers.moonshot import MoonshotOfficialClient


def test_classified_temporary_failure_exposes_bounded_retry_after_without_retrying():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '45'}, json={
            'error': {'type': 'engine_overloaded_error', 'message': 'PRIVATE_PAYLOAD'}})
    with MoonshotOfficialClient(api_key='fixture', live_enabled=True, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttemptFailure) as exc:
            client.create_response([], 'kimi-k3', reasoning_effort='low', output_token_ceiling=1024)
    assert exc.value.retryable and exc.value.category == 'temporary_overload'
    assert exc.value.wait_seconds == 45 and exc.value.wait_source == 'retry_after'
    assert len(calls) == 1 and 'PRIVATE_PAYLOAD' not in str(exc.value)


@pytest.mark.parametrize('kind,message,retry,category', [
    ('rate_limit_reached_error', 'organization RPM rate limit', True, 'temporary_rate_limit'),
    ('rate_limit_reached_error', 'organization TPM rate limit', True, 'temporary_rate_limit'),
    ('rate_limit_reached_error', 'organization concurrency rate limit', True, 'temporary_rate_limit'),
    ('rate_limit_reached_error', 'organization TPD rate limit', False, 'quota_exhausted'),
    ('rate_limit_reached_error', 'unknown limit', False, 'rate_limited'),
    ('exceeded_current_quota_error', 'PRIVATE', False, 'quota_exhausted'),
    ('unrecognized', 'RPM', False, 'rate_limited'),
])
def test_classification_fails_closed(kind, message, retry, category):
    with MoonshotOfficialClient(api_key='fixture', live_enabled=True, transport=httpx.MockTransport(
        lambda _: httpx.Response(429, json={'error': {'type': kind, 'message': message}}))) as client:
        with pytest.raises(ProviderAttemptFailure) as exc:
            client.create_response([], 'kimi-k3', reasoning_effort='low', output_token_ceiling=1024)
    assert exc.value.retryable is retry and exc.value.category == category


@pytest.mark.parametrize('header', ['NaN', '-1', '1000000', 'bad'])
def test_invalid_retry_after_is_not_automatically_retried(header):
    with MoonshotOfficialClient(api_key='fixture', live_enabled=True, transport=httpx.MockTransport(
        lambda _: httpx.Response(429, headers={'Retry-After': header}, json={'error': {'type': 'engine_overloaded_error'}}))) as client:
        with pytest.raises(ProviderAttemptFailure) as exc:
            client.create_response([], 'kimi-k3', reasoning_effort='low', output_token_ceiling=1024)
    assert not exc.value.retryable


def failed_attempt():
    from tests.unit.test_kimi_migration_judgment import official_payload
    a = official_payload()['new_attempts'][0]
    a.update(outcome='nonretryable_failure', failure_category='rate_limited', status_code=429,
             provider_response_count=0, successful_decision_count=0, usage_complete_response_count=0,
             observed_model_counts={}, input_usage=None, output_usage=None, total_usage=None,
             cached_input_usage=None, lane_cooldown=True)
    return a


def accepted(journal):
    from llm_abm_sim import concurrent_robustness_v2 as v2
    from llm_abm_sim._concurrent_recovery_kimi_retry import POLICY
    from tests.unit.test_kimi_migration_runtime import running
    s = running(journal)
    a = failed_attempt()
    s.append(journal, 'parallel_attempt_intent', dict(cell_index=12, pair_schedule_position=1, attempt_number=1))
    s.append(journal, 'parallel_attempt_settled', dict(cell_index=12, pair_schedule_position=1, attempt=a, decision=None))
    payload = {'approval': {'path': '/fixture/retry.json', 'sha256': 'b'*64}, **POLICY,
               'legacy_exception': dict(cell_index=12, pair_schedule_position=1, attempt_sha256=v2._json_sha256(a))}
    s.append(journal, 'kimi_retry_policy_accepted', payload)
    return s


def test_policy_preserves_failed_history_and_v6_is_explicit(tmp_path):
    from llm_abm_sim import concurrent_robustness_v2 as v2
    from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, recovery_scope
    from llm_abm_sim._concurrent_recovery_judgment import RecoveryJudgmentV1
    from tests.unit.test_concurrent_recovery_progress import _journal
    from tests.unit.test_kimi_migration_judgment import official_payload
    with recovery_scope(identity := _journal(tmp_path)):
        s = accepted(CampaignJournal.open(identity))
        assert s.status == 'paused' and s.new_attempts[12, 1][0].status_code == 429
        p = official_payload()
        p['new_attempts'][0]['attempt_number'] = 2
        p['new_attempts'].insert(0, failed_attempt())
        p['schema_version'] = 'concurrent-recovery-provider-judgment-v6'
        assert s.kimi_retry_policy is not None
        p['official_retry_policy'] = s.kimi_retry_policy['approval']
        p['judgment_id'] = v2._json_sha256({k: v for k, v in p.items() if k != 'judgment_id'})
        assert RecoveryJudgmentV1.model_validate(p).new_attempts[0].outcome == 'nonretryable_failure'
        p['schema_version'] = 'concurrent-recovery-provider-judgment-v4'
        p.pop('official_retry_policy')
        p['judgment_id'] = v2._json_sha256({k: v for k, v in p.items() if k != 'judgment_id'})
        with pytest.raises(ValueError):
            RecoveryJudgmentV1.model_validate(p)


@pytest.mark.parametrize('failure', ['temporary', 'exhausted', 'quota', 'unknown'])
def test_admitted_runtime_bounded_retry_and_hard_stop(tmp_path, monkeypatch, failure):
    import time

    from llm_abm_sim import _concurrent_recovery_parallel_runtime as runtime
    from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
    from llm_abm_sim.concurrent_message_experiment import _VariantDecisionContext
    from llm_abm_sim.decision import ProviderResponseProvenanceUnknown
    from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter
    from tests.unit.test_concurrent_recovery_progress import _journal
    from tests.unit.test_moonshot_official_adapter import Client
    from tests.unit.test_robustness_provider_adapters import _context

    calls = []
    waits = []
    real_wait = runtime.wait
    monkeypatch.setattr(runtime.v2, '_V2_MONOTONIC', lambda: time.monotonic() * 10000)
    monkeypatch.setattr(runtime.v2, '_V2_SLEEP', lambda seconds: (waits.append(seconds), time.sleep(seconds / 10000)))
    monkeypatch.setattr(runtime, 'wait', lambda fs, timeout=None, **kw: real_wait(fs, timeout=None if timeout is None else timeout / 10000, **kw))
    class Transport(Client):
        external_provider_client = True
        output_token_ceiling_enforcement = 'wire_only'

        def create_response(self, *args, **kwargs):
            calls.append(time.monotonic() * 10000)
            if failure == 'unknown':
                raise ProviderResponseProvenanceUnknown('fixture')
            if failure in ('exhausted', 'quota') or len(calls) == 1:
                raise ProviderAttemptFailure(category='quota_exhausted' if failure == 'quota' else 'temporary_overload',
                                             retryable=failure != 'quota', status_code=429, lane_cooldown=True)
            return super().create_response(*args, **kwargs)
    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        state = accepted(journal)
        state.append(journal, 'epoch_admitted', dict(ordinal=len(state.epochs)+1, requested_model=state.current_model,
                     epoch_identity_sha256='c'*64, plan_path='/fixture/retry-epoch.json', plan_sha256='c'*64))
        cell = state.cells[12]
        data = _context()
        context = _VariantDecisionContext(decision_variant='primary', prompt_token=cell.prompt_version,
                  **{k: data[k] for k in ('post', 'profile', 'peer_context', 'platform_context')})
        # A single unresolved frozen pair isolates retry timing from independent workers.
        row = state.parallel_batches[12, 0]['pairs'][1]
        work = (runtime.FrozenWork(row['coordinates'], context),)
        state.parallel_batches[12, 0]['pairs'] = [w.reservation() for w in work]
        clients = [Transport() for _ in range(5)]
        for client in clients:
            client.external_provider_client = True
            client.output_token_ceiling_enforcement = 'wire_only'
        pool = runtime.ParallelAdapterPool(tuple(OfficialKimiDecisionAdapter(prompt_version=cell.prompt_version, client=c) for c in clients))
        def run():
            runtime.run_frozen_batch(state=state, journal=journal, pool=pool, work=work,
                                     check_dispatch_window=lambda: None, backoff_seconds=0)
        if failure == 'temporary':
            run()
            assert len(calls) == 2
            attempts = state.attempts((12, 1))
            assert [a.attempt_number for a in attempts] == [1, 2, 3]
            assert attempts[1].wait_seconds == 60
            assert calls[1] - calls[0] >= 60
            run()
            assert len(calls) == 2
        else:
            with pytest.raises((RecoveryCampaignError, runtime.v2._V2CellStopped)):
                run()
            count = len(calls)
            assert count == (2 if failure == 'exhausted' else 1)
            assert state.status == ('reconciliation_required' if failure == 'unknown' else 'stopped')
            if failure == 'exhausted':
                assert state.attempts((12, 1))[-1].outcome == 'attempts_exhausted'
            with pytest.raises((RecoveryCampaignError, runtime.v2._V2CellStopped)):
                run()
            assert len(calls) == count
