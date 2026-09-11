"""Explicitly admitted Study-owned Kimi retries; transport stays single-attempt."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import concurrent_robustness_v2 as v2
from ._concurrent_recovery_campaign import RecoveryCampaignError

EVENT = 'kimi_retry_policy_accepted'
TEMPORARY = {'temporary_rate_limit', 'temporary_overload'}
POLICY = {'maximum_historical_attempts': 3, 'maximum_active_lanes': 2,
          'minimum_dispatch_interval_seconds': 3, 'backoff_base_seconds': 30,
          'maximum_spend_cny': 100, 'unknown_or_quota_stops': True,
          'other_models_enabled': False, 'production_deploy_eligible': False}


def _require(ok: bool) -> None:
    if not ok:
        raise RecoveryCampaignError('Kimi retry policy differs from its exact approved history')


def transition(state: Any, payload: dict[str, Any]) -> Any:
    state._exact(payload, {'approval', 'legacy_exception', *POLICY})
    state._exact(payload['approval'], {'path', 'sha256'})
    v2._require_sha256(payload['approval']['sha256'], 'Kimi retry approval')
    _require(v2._json_sha256({k: payload[k] for k in POLICY}) == v2._json_sha256(POLICY))
    _require(state.kimi_retry_policy is None and state.kimi_migration_active and not state.task_revoked
             and state.status == 'stopped' and not state.has_inflight
             and state.reservation is None and state.pending_judgment is None and state.pending_realized is None
             and state.current_model == 'kimi-coding/k3-256k'
             and isinstance(payload['approval']['path'], str) and payload['approval']['path'].startswith('/'))
    old = payload['legacy_exception']
    state._exact(old, {'cell_index', 'pair_schedule_position', 'attempt_sha256'})
    key = state._parallel_key(old)
    prior = state.attempts(key)
    _require(len(prior) == 1 and prior[0].attempt_number == 1 and key not in state.success_decisions
             and key not in state.old_successes and key not in state.kimi_archived_unknown
             and state.cells[key[0]].requested_model == state.current_model
             and prior[0].provider_route == 'moonshot_official' and prior[0].status_code == 429
             and prior[0].failure_category == 'rate_limited' and prior[0].outcome == 'nonretryable_failure'
             and old['attempt_sha256'] == v2._json_sha256(prior[0].model_dump(mode='json')))
    unresolved_failures = {k for k, a in state.new_attempts.items() if a and a[-1].provider_route == 'moonshot_official' and a[-1].outcome != 'succeeded'}
    _require(unresolved_failures == {key})
    _require(state.kimi_migration_approval['maximum_spend_cny'] == POLICY['maximum_spend_cny'])
    def accept() -> None:
        state.kimi_retry_policy = deepcopy(payload)
        state.status = 'paused'
    return accept


def validate_receipt(origins: Any, state: Any, payload: dict[str, Any], when: Any, head: str) -> None:
    from . import concurrent_robustness_formal_execution as formal
    from . import concurrent_robustness_recovery_task as task
    from ._concurrent_recovery_kimi_migration import _evidence

    a = _evidence(payload['approval'])
    state._exact(a, {'schema_version', 'status', 'user_confirmation', 'recorded_at_utc', 'plan',
                     'expected_head_sha256', 'legacy_exception', *POLICY})
    _require(a['schema_version'] == 'kimi-bounded-retry-consent-v1' and a['status'] == 'approved'
             and isinstance(a['user_confirmation'], str) and bool(a['user_confirmation'].strip())
             and a['expected_head_sha256'] == head and a['plan'] == origins.handoff.model_dump(mode='json')
             and origins.task_plan is not None and task._current(origins.task_plan, when)
             and all(a[k] == payload[k] for k in ('legacy_exception', *POLICY))
             and formal._parse_utc(origins.task_plan['authorization']['approved_at_utc'], 'task approval') <= formal._parse_utc(a['recorded_at_utc'], 'retry approval') <= when)
    transition(state, payload)


def permitted_prior(state: Any, key: tuple[int, int]) -> bool:
    grant = state.kimi_retry_policy
    if grant is None:
        return False
    rows = state.attempts(key)
    if not rows or state.next_attempt_number(key) > 3:
        return False
    if rows[-1].outcome == 'retryable_failure':
        return rows[-1].provider_route == 'moonshot_official' and rows[-1].failure_category in TEMPORARY
    old = grant['legacy_exception']
    return (len(rows) == 1 and key == (old['cell_index'], old['pair_schedule_position'])
            and v2._json_sha256(rows[0].model_dump(mode='json')) == old['attempt_sha256'])


def judgment_reference(state: Any, key: tuple[int, int]) -> dict[str, Any] | None:
    rows = state.new_attempts.get(key, [])
    if state.kimi_retry_policy is not None and len(rows) > 1 and any(
        x.provider_route == 'moonshot_official' and x.outcome != 'succeeded' for x in rows[:-1]
    ):
        return state.kimi_retry_policy['approval']
    return None
