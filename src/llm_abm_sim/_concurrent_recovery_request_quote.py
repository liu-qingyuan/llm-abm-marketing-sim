"""Study-owned auxiliary request estimates; never Formal usage or invoice facts."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import concurrent_robustness_v2 as v2
from ._concurrent_recovery_campaign import RecoveryCampaignError

_FIELDS = {'cell_index', 'pair_schedule_position', 'context_sha256', 'request_sha256'}


def reserve(quote: dict[str, Any]) -> int:
    """Buffered estimate, not a guaranteed upper bound on provider charges."""
    return min(1048576, 2 * quote['estimated_input_tokens'] + 1024) * 20 + 1024 * 100


def transition(state: Any, kind: str, payload: dict[str, Any]) -> Any:
    extra = {'estimated_input_tokens'} if kind == 'kimi_estimate_settled' else (
        {'failure'} if kind == 'kimi_estimate_failed' else set())
    state._exact(payload, _FIELDS | extra)
    key = state._parallel_key(payload)
    for field in ('context_sha256', 'request_sha256'):
        v2._require_sha256(payload[field], 'Kimi request estimate')
    if (not state.kimi_migration_active or state.current_model != 'kimi-coding/k3-256k'
        or state.cells[key[0]].requested_model != state.current_model):
        raise RecoveryCampaignError('Request estimate is outside active official Kimi')
    identity = {field: payload[field] for field in _FIELDS}
    if kind == 'kimi_estimate_intent':
        batch = state.parallel_batches.get(state.parallel_active_batch, {})
        row = next((r for r in batch.get('pairs', []) if (
            r['coordinates']['cell_index'], r['coordinates']['pair_schedule_position']) == key), None)
        if (state.status != 'running' or state.task_revoked or state.has_inflight
            or key in state.kimi_request_quotes or key in state.success_decisions or key in state.old_successes
            or row is None or row['context_sha256'] != payload['context_sha256']):
            raise RecoveryCampaignError('Request estimate lacks unique active frozen input')
        return lambda: setattr(state, 'kimi_estimate_inflight', deepcopy(identity))
    if state.kimi_estimate_inflight != identity:
        raise RecoveryCampaignError('Request estimate result lacks matching intent')
    if kind == 'kimi_estimate_settled':
        n = payload['estimated_input_tokens']
        if type(n) is not int or not 0 < n <= 1048576:
            raise RecoveryCampaignError('Request estimate token count is invalid')
        def apply() -> None:
            state.kimi_request_quotes[key] = deepcopy(payload)
            state.kimi_estimate_inflight = None
        return apply
    if kind != 'kimi_estimate_failed' or payload['failure'] not in {'estimate_failed', 'estimate_unknown', 'request_drift'}:
        raise RecoveryCampaignError('Invalid auxiliary estimate failure')
    def stop() -> None:
        state.kimi_estimate_inflight = None
        state.status = 'stopped'
    return stop


def prepare_batch(state: Any, journal: Any, work: Any, client: Any, check: Any) -> None:
    """Persist one auxiliary intent before each explicit estimate, reuse on replay."""
    from .prompting import build_engagement_prompt
    from .providers.moonshot import MoonshotOfficialClient

    for item in work:
        if item.key in state.old_successes or item.key in state.success_decisions:
            continue
        check()
        messages = build_engagement_prompt(item.context.decision_input(time_step=item.coordinates['time_step']))
        kwargs: dict[str, Any] = dict(reasoning_effort='low', output_token_ceiling=1024)
        digest = MoonshotOfficialClient.request_sha256(messages, 'kimi-k3', **kwargs)
        identity = {'cell_index': item.key[0], 'pair_schedule_position': item.key[1],
                    'context_sha256': item.reservation()['context_sha256'], 'request_sha256': digest}
        old = state.kimi_request_quotes.get(item.key)
        if old is not None:
            if any(old[k] != value for k, value in identity.items()):
                raise RecoveryCampaignError('Persisted request estimate input drift')
            continue
        state.append(journal, 'kimi_estimate_intent', identity)
        try:
            quote = client.estimate_request(messages, 'kimi-k3', **kwargs)
        except Exception:
            state.append(journal, 'kimi_estimate_failed', {**identity, 'failure': 'estimate_failed'})
            raise RecoveryCampaignError('Official request estimate failed; no Formal dispatched') from None
        if quote.request_sha256 != digest or quote.output_token_ceiling != 1024 or quote.is_invoice is not False:
            state.append(journal, 'kimi_estimate_failed', {**identity, 'failure': 'request_drift'})
            raise RecoveryCampaignError('Official request estimate contract drift')
        state.append(journal, 'kimi_estimate_settled', {**identity, 'estimated_input_tokens': quote.estimated_input_tokens})
