"""One explicit Kimi 256-to-1024 amendment; never renews Formal budgets."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any

from . import concurrent_robustness_formal_execution as formal
from . import concurrent_robustness_v2 as v2
from ._concurrent_recovery_campaign import RecoveryCampaignError
from ._concurrent_recovery_recheck import _checked
from .decision import LLMDecisionAdapter

if TYPE_CHECKING:
    from ._concurrent_recovery_progress import CampaignProgress
    from .concurrent_robustness_recovery_execution import _Origins

MODEL = 'kimi-coding/k3-256k'
EVENT = 'kimi_output_amendment_accepted'
FIELDS = {'requested_model', 'output_token_ceiling', 'additional_self_check_cap'}


def transition(state: CampaignProgress, payload: dict[str, Any]) -> Callable[[], None]:
    state._exact(payload, {'approval', *FIELDS})
    state._exact(payload['approval'], {'path', 'sha256'})
    v2._require_sha256(payload['approval']['sha256'], 'output amendment')
    old = state.self_checks.get(MODEL)
    if (state.output_amendment is not None or state.model_lane_approval is None
        or state.current_model != MODEL or state.status != 'stopped' or state.task_revoked
        or state.has_inflight or state.parallel_unknown or state.self_check_inflight is not None
        or state.reservation is not None or state.pending_judgment is not None
        or state.pending_realized is not None or state.parallel_active_batch is not None
        or state.quota_retry_pending is not None or old is None
        or old['attempt']['outcome'] != 'nonretryable_failure'
        or old['attempt']['failure_category'] != 'output_ceiling_exceeded'
        or any(state.prefix[i] for i, c in enumerate(state.cells) if c.requested_model == MODEL)
        or any(state.cells[k[0]].requested_model == MODEL for k in state.new_attempts)
        or payload['requested_model'] != MODEL or type(payload['output_token_ceiling']) is not int
        or payload['output_token_ceiling'] != 1024 or type(payload['additional_self_check_cap']) is not int
        or payload['additional_self_check_cap'] != 1
        or not isinstance(payload['approval']['path'], str) or not payload['approval']['path'].startswith('/')):
        raise RecoveryCampaignError('Output amendment requires the untouched Kimi 256 self-check stop')
    def accept() -> None:
        state.output_amendment = deepcopy(payload)
        state.status = 'ready'
    return accept


def validate_receipt(origins: _Origins, state: CampaignProgress, payload: dict[str, Any], when: datetime, head: str) -> None:
    from . import concurrent_robustness_recovery_task as task
    state._exact(payload, {'approval', *FIELDS})
    approval = _checked(payload['approval'])
    expected = {'schema_version', 'status', 'authorization_reference', 'approved_at_utc', 'task_plan',
                'stopped_head_sha256', 'original_self_check_sha256', 'previous_output_token_ceiling', *FIELDS}
    if (set(approval) != expected or approval['schema_version'] != 'concurrent-recovery-kimi-output-amendment-v1'
        or approval['status'] != 'approved' or origins.task_plan is None
        or approval['task_plan'] != origins.handoff.model_dump(mode='json')
        or approval['stopped_head_sha256'] != head or not task._current(origins.task_plan, when)
        or approval['previous_output_token_ceiling'] != 256
        or approval['original_self_check_sha256'] != v2._json_sha256(state.self_checks.get(MODEL))
        or any(approval[k] != payload[k] for k in FIELDS)):
        raise RecoveryCampaignError('Output amendment differs from original task, stop or self-check')
    reference = approval['authorization_reference']
    formal._safe_reference(reference, 'output amendment authorization')
    if not reference or reference.startswith('REPLACE-'):
        raise RecoveryCampaignError('Output amendment requires explicit user confirmation')
    approved = formal._parse_utc(approval['approved_at_utc'], 'output amendment time')
    start = formal._parse_utc(origins.task_plan['authorization']['approved_at_utc'], 'task approval time')
    if not start <= approved <= when:
        raise RecoveryCampaignError('Output amendment time is crossed')
    transition(state, payload)


def check_transition(state: CampaignProgress, kind: str, payload: dict[str, Any]) -> Callable[[], None]:
    if (state.output_amendment is None or state.current_model != MODEL or state.task_revoked
        or state.status not in {'ready', 'checkpoint'} or state.has_inflight):
        raise RecoveryCampaignError('Amended self-check is outside its approved state')
    if kind == 'amended_self_check_intent':
        state._exact(payload, {'requested_model', 'contract_sha256'})
        if payload['requested_model'] != MODEL or state.amended_self_check_intent is not None or state.self_check_inflight is not None:
            raise RecoveryCampaignError('Only one additional self-check is approved')
        v2._require_sha256(payload['contract_sha256'], 'amended self-check contract')
        def start() -> None:
            state.amended_self_check_intent = deepcopy(payload)
            state.self_check_inflight = MODEL
        return start
    state._exact(payload, {'requested_model', 'attempt', 'decision'})
    if (payload['requested_model'] != MODEL or state.self_check_inflight != MODEL
        or state.amended_self_check_intent is None or state.amended_self_check is not None):
        raise RecoveryCampaignError('Amended self-check lacks a unique unsettled intent')
    row = v2._V2AttemptEvidence.model_validate(payload['attempt'])
    if (row.attempt_number != 1 or row.outcome not in {'succeeded', 'nonretryable_failure'}
        or (row.outcome == 'succeeded') != (payload['decision'] is not None)):
        raise RecoveryCampaignError('Additional self-check permits one attempt and zero retries')
    def finish() -> None:
        state.amended_self_check = deepcopy(payload)
        state.self_check_inflight = None
        if row.outcome != 'succeeded':
            state.status = 'stopped'
    return finish


def judgment_reference(state: CampaignProgress, model: str) -> dict[str, Any] | None:
    return state.output_amendment['approval'] if state.output_amendment is not None and model == MODEL else None


def preflight(state: CampaignProgress, adapters: Mapping[str, LLMDecisionAdapter]) -> None:
    """Compare transport-facing evidence with the ledger-owned amended condition."""
    if state.output_amendment is None or state.current_model != MODEL:
        return
    from ._concurrent_recovery_parallel_runtime import ParallelAdapterPool
    for adapter in adapters.values():
        for leaf in adapter.lanes if isinstance(adapter, ParallelAdapterPool) else (adapter,):
            evidence = getattr(leaf, 'request_evidence', {})
            expected = {'requested_model': MODEL, 'output_token_ceiling': 1024,
                        'wire_output_token_ceiling': 1024, 'output_token_ceiling_scope': 'total_completion_tokens',
                        'reasoning_effort': 'low', 'thinking_budget': None}
            if any(evidence.get(k) != value for k, value in expected.items()):
                raise RecoveryCampaignError('Adapter differs from the approved Kimi output condition')
