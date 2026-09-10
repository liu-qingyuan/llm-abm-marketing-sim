from copy import deepcopy

import pytest

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from tests.unit.test_concurrent_recovery_progress import _journal
from tests.unit.test_kimi_manual_retry_runtime import stopped


def test_approved_kimi_rebuilds_identical_prior_barrier_once(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, payload = stopped(journal)
        state.append(journal, 'kimi_manual_retry_accepted', payload)
        # State fixture for the original already committed first batch followed
        # by a newly admitted epoch. The original runtime owns full commit shape.
        commit = {'fixture_commit': 'unchanged'}
        state.batch_commits[len(state.epochs), 12, 0] = deepcopy(commit)
        state.epochs.append(deepcopy(state.epochs[-1]))
        state.prefix[12] = 60
        state.status = 'running'
        state.parallel_active_batch = (12, 1)
        before = state.physical_attempts
        state.append(journal, 'batch_committed', {'cell_index': 12, 'time_step': 0, 'commit': commit})
        assert state.parallel_active_batch == (12, 1) and state.physical_attempts == before
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'batch_committed', {'cell_index': 12, 'time_step': 0, 'commit': commit})


@pytest.mark.parametrize('fault', ['unapproved', 'changed', 'missing', 'future', 'foreign'])
def test_kimi_replay_does_not_relax_barrier_identity_or_scope(tmp_path, fault):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, payload = stopped(journal)
        state.append(journal, 'kimi_manual_retry_accepted', payload)
        commit = {'fixture_commit': 'unchanged'}
        epoch = len(state.epochs)
        state.batch_commits[epoch, 12, 0] = deepcopy(commit)
        state.epochs.append(deepcopy(state.epochs[-1]))
        state.prefix[12] = 60
        state.status = 'running'
        state.parallel_active_batch = (12, 1)
        index = 12
        if fault == 'unapproved':
            state.kimi_manual_retry_approval = None
        elif fault == 'changed':
            commit['fixture_commit'] = 'changed'
        elif fault == 'missing':
            del state.batch_commits[epoch, 12, 0]
        elif fault == 'future':
            state.batch_commits[epoch + 2, 12, 0] = state.batch_commits.pop((epoch, 12, 0))
        else:
            index = 4
        before = deepcopy(state.__dict__)
        head = journal.head
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'batch_committed', {'cell_index': index, 'time_step': 0, 'commit': commit})
        assert journal.head == head and state.__dict__ == before
