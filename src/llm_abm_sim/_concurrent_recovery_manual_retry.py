"""Study-owned, single-use reconciliation of explicitly approved unknown intents.

An archived intent stays unknown and charged to physical/cash guards. Acceptance
never opens a provider client or fabricates a response. Only ordinal two is
admitted; the normal runtime retains all success reuse and hard-stop behavior.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import concurrent_robustness_v2 as v2
from ._concurrent_recovery_campaign import RecoveryCampaignError
from ._concurrent_recovery_judgment import UnknownAttemptReference

if TYPE_CHECKING:
    from ._concurrent_recovery_progress import CampaignProgress

EVENT = 'kimi_manual_retry_accepted'
MODEL = 'kimi-coding/k3-256k'


def require(ok: bool) -> None:
    if not ok:
        raise RecoveryCampaignError('Manual Kimi retry must match its exact approved unknown history')


def transition(state: CampaignProgress, payload: dict[str, Any]) -> Callable[[], None]:
    state._exact(payload, {'approval', 'unknown_intents'})
    state._exact(payload['approval'], {'path', 'sha256'})
    v2._require_sha256(payload['approval']['sha256'], 'manual retry approval')
    require(isinstance(payload['approval']['path'], str) and Path(payload['approval']['path']).is_absolute())
    require(state.kimi_migration_active and state.kimi_manual_retry_approval is None
            and state.status == 'reconciliation_required' and not state.task_revoked
            and state.inflight is None and state.self_check_inflight is None
            and state.reservation is None and state.pending_judgment is None and state.pending_realized is None
            and state.parallel_active_batch is not None and not state.kimi_archived_unknown)
    rows = payload['unknown_intents']
    require(isinstance(rows, list) and len(rows) == 4 and len(state.parallel_inflight) == 4)
    archive = {}
    for row in rows:
        state._exact(row, {'cell_index', 'pair_schedule_position', 'attempt_number', 'intent_sha256'})
        key = state._parallel_key(row)
        require(type(row['attempt_number']) is int and row['attempt_number'] == 1
                and state.parallel_inflight.get(key) == 1 and key not in archive
                and state.cells[key[0]].requested_model == MODEL
                and (key[0], key[1] // (state.per_cell // 30)) == state.parallel_active_batch
                and not state.attempts(key) and key not in state.old_successes
                and key not in state.success_decisions and key not in state.judgments)
        v2._require_sha256(row['intent_sha256'], 'unknown intent')
        archive[key] = {'attempt_number': 1, 'intent_sha256': row['intent_sha256']}
    require(set(archive) == set(state.parallel_inflight) and state.parallel_unknown <= set(archive))
    def apply() -> None:
        state.kimi_manual_retry_approval = deepcopy(payload['approval'])
        state.kimi_archived_unknown = deepcopy(archive)
        state.parallel_inflight.clear()
        state.parallel_unknown.clear()
        state.status = 'paused'
    return apply


def judgment_fields(state: CampaignProgress, key: tuple[int, int]) -> dict[str, Any]:
    row = state.kimi_archived_unknown.get(key)
    if row is None:
        return {'manual_retry_approval': None, 'unknown_attempts': ()}
    return {'manual_retry_approval': state.kimi_manual_retry_approval,
            'unknown_attempts': (UnknownAttemptReference.model_validate(row),)}


def validate_receipt(origins: Any, state: CampaignProgress, payload: dict[str, Any], when: Any, head: str) -> None:
    from . import concurrent_robustness_recovery_task as task
    from ._concurrent_recovery_kimi_migration import _evidence
    approval = _evidence(payload['approval'])
    require(approval['schema_version'] == 'kimi-manual-unknown-retry-user-consent-v1'
            and approval['status'] == 'user_approved_pending_runtime_admission'
            and approval['stopped_head']['record_sha256'] == head
            and origins.task_plan is not None and task._current(origins.task_plan, when)
            and approval['original_plan'] == origins.handoff.model_dump(mode='json')
            and approval['additional_attempts_per_listed_logical'] == 1
            and type(approval['additional_attempts_per_listed_logical']) is int
            and approval['maximum_historical_attempts_per_logical'] == 3
            and approval['automatic_retries'] == 0 and approval['maximum_inflight'] == 5
            and state.kimi_migration_approval is not None
            and approval['maximum_spend_cny'] == state.kimi_migration_approval['maximum_spend_cny']
            and approval['cash_cap_increase_authorized'] is False
            and approval['usage_unknown_preserved'] is True
            and approval['other_models_enabled'] is False
            and approval['production_deploy_eligible'] is False
            and approval['goal'] == {'judgments': 7200, 'cells': 4, 'complete_barriers': 120})
    from datetime import datetime, timedelta
    approved_at = datetime.fromisoformat(approval['recorded_at_utc'])
    require(approved_at.tzinfo is not None and approved_at.utcoffset() == timedelta(0) and approved_at <= when)
    expected = [{k: row[k] for k in ('cell_index', 'pair_schedule_position', 'attempt_number', 'intent_sha256')}
                for row in approval['unknown_intents']]
    require(payload['unknown_intents'] == expected)
    # Events are drawn only from the original explicit control root and the
    # receipt's frozen prefix, not a scanned latest campaign or another source.
    from ._concurrent_recovery_campaign import _read
    sequence = approval['stopped_head']['sequence']
    require(type(sequence) is int and sequence > 0)
    records = {}
    previous = origins.campaign['campaign_identity_sha256']
    for number in range(1, sequence + 1):
        event = _read(Path(origins.campaign['control_root']) / 'events' / f'{number:08d}.json')
        body = {k: value for k, value in event.items() if k != 'record_sha256'}
        require(event['sequence'] == number and event['previous_sha256'] == previous
                and event['record_sha256'] == v2._json_sha256(body)
                and event['campaign_identity_sha256'] == origins.campaign['campaign_identity_sha256'])
        records[event['record_sha256']] = event
        previous = event['record_sha256']
    require(previous == head)
    require(head in records and records[head]['kind'] == 'epoch_finished'
            and type(approval['stopped_head']['sequence']) is int
            and records[head]['sequence'] == approval['stopped_head']['sequence'])
    for row in approval['unknown_intents']:
        event = records.get(row['intent_sha256'])
        require(event is not None)
        assert event is not None
        require(event['kind'] == 'parallel_attempt_intent' and event['recorded_at_utc'] == row['recorded_at_utc']
                and event['payload'] == {k: row[k] for k in ('cell_index', 'pair_schedule_position', 'attempt_number')})
    import hashlib

    from .decision import EngageDecision
    preserved = {}
    for row in approval['preserved_successes']:
        key = row['cell_index'], row['pair_schedule_position']
        require(key not in preserved and key in state.success_decisions)
        attempts = state.new_attempts.get(key, [])
        require(bool(attempts) and attempts[-1].outcome == 'succeeded')
        event = records.get(row['event_sha256'])
        require(event is not None)
        assert event is not None
        require(event['kind'] == 'parallel_attempt_settled'
                and event['payload']['cell_index'] == key[0] and event['payload']['pair_schedule_position'] == key[1]
                and v2._V2AttemptEvidence.model_validate(event['payload']['attempt']) == attempts[-1]
                and EngageDecision.model_validate(event['payload']['decision']) == state.success_decisions[key]
                and # The original user receipt hashes compact JSON without the journal newline.
                row['attempt_sha256'] == hashlib.sha256(v2._canonical_json_bytes(event['payload']['attempt'])[:-1]).hexdigest())
        preserved[key] = row
    require(set(preserved) == {key for key in state.success_decisions if state.cells[key[0]].requested_model == MODEL})
    transition(state, payload)
