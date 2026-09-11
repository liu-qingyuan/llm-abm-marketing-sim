from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, recovery_scope
from tests.unit.test_concurrent_recovery_progress import _journal
from tests.unit.test_kimi_manual_retry_runtime import stopped


def test_quote_reprices_unknown_without_inventing_usage(tmp_path):
    from llm_abm_sim._concurrent_recovery_kimi_migration import cash_budget
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, approval = stopped(journal)
        state.append(journal, 'kimi_manual_retry_accepted', approval)
        state.status = 'running'
        physical = state.physical_attempts
        from copy import deepcopy
        replay = deepcopy(state)
        sequence = len(journal.records)
        for key in state.kimi_archived_unknown:
            row = state.parallel_batches[12, 0]['pairs'][key[1]]
            intent = dict(cell_index=12, pair_schedule_position=key[1],
                          context_sha256=row['context_sha256'], request_sha256='a'*64)
            state.append(journal, 'kimi_estimate_intent', intent)
            state.append(journal, 'kimi_estimate_settled', {**intent, 'estimated_input_tokens': 659})
        budget = cash_budget(state, (12, 10))
        assert budget['can_reserve_one']
        assert budget['unpriced_settled_requests'] == 4
        assert budget['settled_upper_micro_cny'] == 4 * ((659*2+1024)*20+1024*100)
        assert state.physical_attempts == physical
        assert len(state.kimi_archived_unknown) == 4 and not state.has_inflight
        for event in CampaignJournal.read(identity).records[sequence:]:
            replay.transition(event['kind'], event['payload'])()
        assert replay.__dict__ == state.__dict__
        assert cash_budget(replay, (12, 10)) == budget


def test_quote_order_hash_and_failure_are_fail_closed(tmp_path):
    from copy import deepcopy

    import pytest

    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError
    from tests.unit.test_kimi_migration_runtime import running
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = running(journal)
        row = state.parallel_batches[12, 0]['pairs'][1]
        intent = dict(cell_index=12, pair_schedule_position=1, context_sha256=row['context_sha256'], request_sha256='b'*64)
        before = state.physical_attempts
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'kimi_estimate_settled', {**intent, 'estimated_input_tokens': 659})
        state.append(journal, 'kimi_estimate_intent', intent)
        assert state.has_inflight
        snapshot = deepcopy(state.__dict__)
        for change in ({'request_sha256': 'c'*64}, {'estimated_input_tokens': True}, {'estimated_input_tokens': 0}):
            with pytest.raises((RecoveryCampaignError, ValueError)):
                state.append(journal, 'kimi_estimate_settled', {**intent, 'estimated_input_tokens': 659, **change})
            assert state.__dict__ == snapshot
        state.append(journal, 'kimi_estimate_failed', {**intent, 'failure': 'estimate_failed'})
        assert state.status == 'stopped' and not state.has_inflight and not state.kimi_request_quotes
        assert state.physical_attempts == before
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'kimi_estimate_intent', intent)


def test_over_quote_usage_retains_success_and_stops(tmp_path):
    from tests.unit.test_kimi_migration_judgment import official_payload
    from tests.unit.test_kimi_migration_runtime import running
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = running(journal)
        row = state.parallel_batches[12, 0]['pairs'][1]
        intent = dict(cell_index=12, pair_schedule_position=1, context_sha256=row['context_sha256'], request_sha256='b'*64)
        state.append(journal, 'kimi_estimate_intent', intent)
        state.append(journal, 'kimi_estimate_settled', {**intent, 'estimated_input_tokens': 1})
        state.append(journal, 'parallel_attempt_intent', dict(cell_index=12, pair_schedule_position=1, attempt_number=1))
        p = official_payload()
        attempt = p['new_attempts'][0]
        attempt['input_usage'] = 20000
        attempt['total_usage'] = attempt['input_usage'] + attempt['output_usage']
        state.append(journal, 'parallel_attempt_settled', dict(cell_index=12, pair_schedule_position=1,
                     attempt=attempt, decision=p['decision']))
        assert state.status == 'stopped' and (12, 1) in state.success_decisions
        assert not state.has_inflight


def test_prepare_reuses_quotes_and_failed_estimate_dispatches_no_chat(tmp_path):
    import pytest

    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError
    from llm_abm_sim._concurrent_recovery_parallel_runtime import FrozenWork
    from llm_abm_sim._concurrent_recovery_request_quote import prepare_batch
    from llm_abm_sim.concurrent_message_experiment import _VariantDecisionContext
    from tests.unit.test_kimi_migration_runtime import running
    from tests.unit.test_moonshot_official_adapter import Client
    from tests.unit.test_robustness_provider_adapters import _context
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = running(journal)
        data = _context()
        context = _VariantDecisionContext(decision_variant='primary', prompt_token=state.cells[12].prompt_version,
                    **{k: data[k] for k in ('post', 'profile', 'peer_context', 'platform_context')})
        work = tuple(FrozenWork(row['coordinates'], context) for row in state.parallel_batches[12, 0]['pairs'])
        state.parallel_batches[12, 0]['pairs'] = [w.reservation() for w in work]
        class Counting(Client):
            estimates = 0
            def estimate_request(self, *args, **kwargs):
                self.estimates += 1
                return super().estimate_request(*args, **kwargs)
        client = Counting()
        physical = state.physical_attempts
        prepare_batch(state, journal, work[:1], client, lambda: None)
        head = journal.head
        prepare_batch(state, journal, work[:1], client, lambda: None)
        assert client.estimates == 1 and journal.head == head and not client.calls
        class Failed(Client):
            def estimate_request(self, *args, **kwargs):
                raise ValueError('PRIVATE_PAYLOAD')
        bad = Failed()
        with pytest.raises(RecoveryCampaignError, match='no Formal dispatched'):
            prepare_batch(state, journal, work[1:2], bad, lambda: None)
        assert state.status == 'stopped' and state.physical_attempts == physical
        assert not bad.calls and not state.has_inflight
        assert 'PRIVATE_PAYLOAD' not in str(journal.records[-1])
