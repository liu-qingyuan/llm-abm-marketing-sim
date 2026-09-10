"""One explicit quota-stop retry, never an automatic quota-recovery policy."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any

from . import concurrent_robustness_formal_execution as formal
from . import concurrent_robustness_v2 as v2
from ._concurrent_recovery_campaign import RecoveryCampaignError
from ._concurrent_recovery_recheck import _checked

if TYPE_CHECKING:
    from ._concurrent_recovery_progress import CampaignProgress
    from .concurrent_robustness_recovery_execution import _Origins

EVENT = 'quota_retry_accepted'


def terms(state: CampaignProgress) -> list[dict[str, Any]]:
    """Identify every unresolved hard failure; only bounded quota failures qualify."""
    if (state.model_lane_approval is not None or state.status != 'stopped' or state.quota_retry_approval is not None
        or state.task_plan is None or state.task_revoked or state.has_inflight
        or state.parallel_unknown or state.self_check_inflight is not None
        or state.pending_judgment is not None or state.pending_realized is not None
        or state.reservation is not None or state.parallel_approval is None
        or state.current_model != 'gemini-3.1-pro' or state.parallel_active_batch is None):
        raise RecoveryCampaignError('Quota retry requires a drained, uniquely stopped parallel Gemini task')
    cap = next(row['maximum_new_physical_attempts'] for row in state.proposal['model_budgets']
               if row['requested_model'] == state.current_model)
    if state.physical_attempts >= state.proposal['maximum_new_physical_attempts'] or state.physical_by_model[state.current_model] >= cap:
        raise RecoveryCampaignError('Quota retry cannot reopen an exhausted physical budget')
    check = state.effective_self_check(state.current_model)
    if check is None or check['attempt']['outcome'] != 'succeeded':
        raise RecoveryCampaignError('Quota retry cannot replace a failed self-check')
    result = []
    for key, attempts in sorted(state.new_attempts.items()):
        last = attempts[-1]
        if last.outcome in {'succeeded', 'retryable_failure'}:
            continue
        if (last.outcome != 'nonretryable_failure' or last.failure_category != 'quota_exhausted'
            or len(state.attempts(key)) >= 3 or key in state.success_decisions
            or key in state.old_successes or key in state.judgments
            or (key[0], key[1] // (state.per_cell // 30)) != state.parallel_active_batch):
            raise RecoveryCampaignError('Quota retry cannot release a different or exhausted hard failure')
        result.append({'cell_index': key[0], 'pair_schedule_position': key[1],
                       'attempt_sha256': v2._json_sha256(last.model_dump(mode='json'))})
    if not 1 <= len(result) <= 4:
        raise RecoveryCampaignError('Quota retry requires one drained batch of exact failed attempts')
    return result


def transition(state: CampaignProgress, payload: dict[str, Any]) -> Callable[[], None]:
    state._exact(payload, {'approval', 'failed_attempts'})
    state._exact(payload['approval'], {'path', 'sha256'})
    v2._require_sha256(payload['approval']['sha256'], 'quota retry approval')
    if (not isinstance(payload['approval']['path'], str) or not payload['approval']['path'].startswith('/')
        or payload['failed_attempts'] != terms(state)):
        raise RecoveryCampaignError('Quota retry differs from its exact failed attempts')
    def accept() -> None:
        state.quota_retry_approval = deepcopy(payload)
        first = payload['failed_attempts'][0]
        state.quota_retry_pending = (first['cell_index'], first['pair_schedule_position'])
        state.status = 'paused'
    return accept


def validate_receipt(origins: _Origins, state: CampaignProgress, payload: dict[str, Any], when: datetime, head: str) -> None:
    from . import concurrent_robustness_recovery_task as task
    state._exact(payload, {'approval', 'failed_attempts'})
    approval = _checked(payload['approval'])
    expected = {'schema_version', 'status', 'authorization_reference', 'approved_at_utc',
                'task_plan', 'stopped_head_sha256', 'failed_attempts', 'initial_formal_attempts',
                'requested_model', 'maximum_inflight', 'stop_after_model', 'additional_probes'}
    if (set(approval) != expected or approval['schema_version'] != 'concurrent-recovery-quota-retry-approval-v1'
        or approval['status'] != 'approved' or origins.task_plan is None
        or approval['task_plan'] != origins.handoff.model_dump(mode='json')
        or approval['stopped_head_sha256'] != head or not task._current(origins.task_plan, when)
        or approval['failed_attempts'] != payload['failed_attempts']
        or type(approval['initial_formal_attempts']) is not int or approval['initial_formal_attempts'] != 1
        or type(approval['maximum_inflight']) is not int or approval['maximum_inflight'] != 4
        or approval['requested_model'] != 'gemini-3.1-pro' or approval['stop_after_model'] is not True
        or type(approval['additional_probes']) is not int or approval['additional_probes'] != 0):
        raise RecoveryCampaignError('Quota retry approval crosses its original task or single-attempt scope')
    reference = approval['authorization_reference']
    formal._safe_reference(reference, 'quota retry authorization reference')
    if not reference or reference.startswith('REPLACE-'):
        raise RecoveryCampaignError('Quota retry requires an explicit user retry reference')
    approved = formal._parse_utc(approval['approved_at_utc'], 'quota retry approval time')
    start = formal._parse_utc(origins.task_plan['authorization']['approved_at_utc'], 'task approval time')
    if not start <= approved <= when:
        raise RecoveryCampaignError('Quota retry approval time is crossed')
    transition(state, payload)


def judgment_reference(state: CampaignProgress, key: tuple[int, int]) -> dict[str, Any] | None:
    """Only approved exact failed-attempt sequences use the new Judgment schema."""
    for receipt in (state.quota_retry_approval, state.gemini_restoration_approval):
        if receipt is None:
            continue
        for row in receipt['failed_attempts']:
            if (row['cell_index'], row['pair_schedule_position']) == key:
                if not any(v2._json_sha256(a.model_dump(mode='json')) == row['attempt_sha256']
                           for a in state.new_attempts.get(key, ())):
                    raise RecoveryCampaignError('Quota Judgment lost its approved original failure')
                return receipt['approval']
    return None
