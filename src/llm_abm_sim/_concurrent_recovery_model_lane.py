"""Explicit Kimi-only lane admission on the original stopped task and ledger.

This is not quota recovery: the Gemini lane remains stopped, its exact batch and
receipts are retained, and no Gemini retry is granted. Study remains the sole
source-lock owner and writer. All lanes share original cumulative counters.
"""
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

EVENT = 'model_lane_accepted'
MODEL = 'kimi-coding/k3-256k'
FIELDS = {'requested_model', 'maximum_inflight', 'global_maximum_inflight', 'stop_after_model'}


def transition(state: CampaignProgress, payload: dict[str, Any]) -> Callable[[], None]:
    state._exact(payload, {'approval', *FIELDS})
    state._exact(payload['approval'], {'path', 'sha256'})
    v2._require_sha256(payload['approval']['sha256'], 'model lane approval')
    if (state.model_lane_approval is not None or state.status != 'stopped'
        or state.task_plan is None or state.task_revoked or state.has_inflight
        or state.parallel_unknown or state.self_check_inflight is not None
        or state.reservation is not None or state.pending_judgment is not None
        or state.pending_realized is not None or state.quota_retry_pending is not None
        or state.current_model != 'gemini-3.1-pro' or state.parallel_approval is None
        or state.parallel_active_batch is None
        or MODEL in state.self_check_intents or MODEL in state.self_checks
        or MODEL not in state.model_order
        or any(state.prefix[i] for i, cell in enumerate(state.cells) if cell.requested_model == MODEL)
        or any(state.cells[key[0]].requested_model == MODEL for key in state.new_attempts)
        or payload['requested_model'] != MODEL or payload['stop_after_model'] is not True
        or type(payload['maximum_inflight']) is not int or not 2 <= payload['maximum_inflight'] <= 10
        or type(payload['global_maximum_inflight']) is not int or payload['global_maximum_inflight'] != 10
        or not isinstance(payload['approval']['path'], str) or not payload['approval']['path'].startswith('/')):
        raise RecoveryCampaignError('Model lane requires untouched Kimi and a drained stopped Gemini task')
    check = state.effective_self_check('gemini-3.1-pro')
    if check is None or check['attempt']['outcome'] != 'succeeded':
        raise RecoveryCampaignError('Model lane cannot bypass a failed Gemini self-check')
    failures = []
    for key, attempts in state.new_attempts.items():
        last = attempts[-1]
        if last.outcome in {'succeeded', 'retryable_failure'}:
            continue
        if (state.cells[key[0]].requested_model != 'gemini-3.1-pro'
            or last.outcome != 'nonretryable_failure' or last.failure_category != 'quota_exhausted'
            or (key[0], key[1] // (state.per_cell // 30)) != state.parallel_active_batch):
            raise RecoveryCampaignError('Model lane cannot bypass a non-quota or foreign hard stop')
        failures.append(key)
    if not failures:
        raise RecoveryCampaignError('Model lane requires persisted Gemini quota evidence')
    cap = next(row['maximum_new_physical_attempts'] for row in state.proposal['model_budgets']
               if row['requested_model'] == MODEL)
    if state.physical_attempts >= state.proposal['maximum_new_physical_attempts'] or state.physical_by_model[MODEL] >= cap:
        raise RecoveryCampaignError('Model lane cannot renew exhausted cumulative budgets')

    def accept() -> None:
        state.suspended_models['gemini-3.1-pro'] = {
            'status': state.status, 'model_index': state.model_index,
            'parallel_active_batch': state.parallel_active_batch,
            'parallel_approval': deepcopy(state.parallel_approval),
            'quota_retry_approval': deepcopy(state.quota_retry_approval),
        }
        state.model_lane_approval = deepcopy(payload)
        state.parallel_active_batch = None
        state.status = 'ready'
    return accept


def validate_receipt(origins: _Origins, state: CampaignProgress, payload: dict[str, Any], when: datetime, head: str) -> None:
    from . import concurrent_robustness_recovery_task as task
    state._exact(payload, {'approval', *FIELDS})
    approval = _checked(payload['approval'])
    expected = {'schema_version', 'status', 'authorization_reference', 'approved_at_utc',
                'task_plan', 'stopped_head_sha256', *FIELDS}
    if (set(approval) != expected or approval['schema_version'] != 'concurrent-recovery-model-lane-approval-v1'
        or approval['status'] != 'approved' or origins.task_plan is None
        or approval['task_plan'] != origins.handoff.model_dump(mode='json')
        or approval['stopped_head_sha256'] != head or not task._current(origins.task_plan, when)
        or any(approval[k] != payload[k] for k in FIELDS)):
        raise RecoveryCampaignError('Model lane approval differs from its original task, head or bounded scope')
    reference = approval['authorization_reference']
    formal._safe_reference(reference, 'model lane authorization reference')
    if not reference or reference.startswith('REPLACE-'):
        raise RecoveryCampaignError('Model lane requires an explicit user confirmation reference')
    approved = formal._parse_utc(approval['approved_at_utc'], 'model lane approval time')
    start = formal._parse_utc(origins.task_plan['authorization']['approved_at_utc'], 'task approval time')
    if not start <= approved <= when:
        raise RecoveryCampaignError('Model lane approval time is crossed')
    transition(state, payload)


def source_guard(facts: list[dict[str, Any]]) -> Callable[[], None]:
    """Verify bound files once, then fail before dispatch on any metadata drift.

    ctime/mtime/inode/bytes/mode detect replacement and in-place writes without
    rehashing large frozen datasets for every single Provider request. Full
    content/origin verification still runs on entry and independent publication.
    """
    from pathlib import Path

    from .concurrent_robustness_recovery import _file_fact

    def stamp(path: Path) -> tuple[int, ...]:
        if path.is_symlink():
            raise RecoveryCampaignError('Model lane source drift detected')
        info = path.stat()
        return info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_mtime_ns, info.st_ctime_ns

    paths = [Path(row['path']) for row in facts]
    before = [stamp(path) for path in paths]
    if any(_file_fact(path) != row for path, row in zip(paths, facts, strict=True)):
        raise RecoveryCampaignError('Model lane source differs from its frozen facts')

    def check() -> None:
        try:
            if [stamp(path) for path in paths] != before:
                raise RecoveryCampaignError('Model lane source drift detected')
        except OSError:
            raise RecoveryCampaignError('Model lane source became unavailable') from None
    check()
    return check
