from copy import deepcopy

import pytest

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from tests.unit.test_concurrent_recovery_gemini_restoration import payload, stopped_kimi
from tests.unit.test_concurrent_recovery_progress import _journal


def completed_gemini(journal):
    state = stopped_kimi(journal)
    state.append(journal, 'gemini_restoration_accepted', payload(state))
    # State-only fixture for the read-only admission invariant checker.
    state.status = 'model_complete'
    state.model_stage_complete = True
    state.quota_retry_pending = None
    state.parallel_active_batch = None
    for i in range(4, 8):
        state.prefix[i] = state.per_cell
    return state


def test_migration_terms_preserve_original_failed_attempt_and_budget(tmp_path):
    from llm_abm_sim._concurrent_recovery_kimi_migration import terms

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = completed_gemini(journal)
        before = deepcopy(state.__dict__)
        result = terms(state)
        assert result['failed_attempts'][0]['cell_index'] == 12
        assert result['failed_attempts'][0]['pair_schedule_position'] == 0
        assert result['remaining_logical_judgments'] == 7200
        assert result['frozen_batch'] == [12, 0]
        assert state.__dict__ == before


@pytest.mark.parametrize('fault', ['inflight', 'unknown', 'revoked', 'budget', 'incomplete', 'pending', 'batch', 'failed_kind'])
def test_migration_terms_reject_other_states(tmp_path, fault):
    from llm_abm_sim._concurrent_recovery_kimi_migration import terms

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        state = completed_gemini(CampaignJournal.open(identity))
        if fault == 'inflight':
            state.parallel_inflight[12, 1] = 1
        elif fault == 'unknown':
            state.parallel_unknown.add((12, 1))
        elif fault == 'revoked':
            state.task_revoked = True
        elif fault == 'budget':
            state.physical_attempts = state.proposal['maximum_new_physical_attempts']
        elif fault == 'incomplete':
            state.prefix[7] -= 1
        elif fault == 'pending':
            state.quota_retry_pending = (4, 0)
        elif fault == 'batch':
            state.suspended_models['kimi-coding/k3-256k']['parallel_active_batch'] = (12, 1)
        else:
            state.new_attempts[12, 0][0] = state.new_attempts[12, 0][0].model_copy(update={'status_code': 401})
        with pytest.raises(RecoveryCampaignError):
            terms(state)
