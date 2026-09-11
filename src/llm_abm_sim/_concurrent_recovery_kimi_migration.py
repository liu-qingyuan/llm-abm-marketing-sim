"""Kimi migration invariants over the original, fully replayed Study state.

This Module owns migration terms and hash-bound authorization admission.
Admission never opens credentials, dispatches work, or activates a model.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import TYPE_CHECKING, Any, cast

from . import concurrent_robustness_v2 as v2
from ._concurrent_recovery_campaign import RecoveryCampaignError

if TYPE_CHECKING:
    from ._concurrent_recovery_progress import CampaignProgress

MODEL = "kimi-coding/k3-256k"
OFFICIAL_MODEL = "kimi-k3"


def _require(condition: bool) -> None:
    if not condition:
        raise RecoveryCampaignError("Kimi migration requires the drained original lane after Gemini completion")


def terms(state: CampaignProgress) -> dict[str, Any]:
    """Return exact preserved attempts and remaining budget, without changing them.

    Only a completed restored Gemini stage and its original suspended Kimi first
    batch qualify. No later Kimi stop, unknown attempt, or exhausted budget can be
    transformed into fresh capacity by preparing these terms.
    """
    suspended = state.suspended_models.get(MODEL)
    _require(
        state.status == "model_complete" and state.model_stage_complete
        and state.current_model == "gemini-3.1-pro"
        and state.gemini_restoration_approval is not None
        and state.task_plan is not None and not state.task_revoked
        and not state.has_inflight and not state.parallel_unknown
        and state.self_check_inflight is None and state.reservation is None
        and state.pending_judgment is None and state.pending_realized is None
        and state.quota_retry_pending is None and state.parallel_active_batch is None
        and suspended is not None
    )
    assert suspended is not None
    indexes = [i for i, cell in enumerate(state.cells) if cell.requested_model == MODEL]
    gemini = [i for i, cell in enumerate(state.cells) if cell.requested_model == "gemini-3.1-pro"]
    _require(
        len(indexes) == 4 and len(gemini) == 4
        and all(state.prefix[i] == state.per_cell for i in gemini)
        and all(state.prefix[i] == 0 for i in indexes)
        and suspended["status"] == "stopped"
        and suspended["model_lane_approval"] == state.model_lane_approval
        and suspended["output_amendment"] == state.output_amendment
        and suspended["parallel_active_batch"] == (indexes[0], 0)
        and (indexes[0], 0) in state.parallel_batches
    )
    check = state.effective_self_check(MODEL)
    _require(check is not None and check["attempt"]["outcome"] == "succeeded")
    preserved_successes = []
    failed_attempts = []
    for key, attempts in sorted(state.new_attempts.items()):
        if key[0] not in indexes:
            continue
        _require(
            len(attempts) == 1 and attempts[0].attempt_number == 1
            and key[0] == indexes[0] and 0 <= key[1] < state.per_cell // 30
            and key not in state.old_successes and key not in state.judgments
        )
        row = attempts[0]
        fact = {"cell_index": key[0], "pair_schedule_position": key[1],
                "attempt_sha256": v2._json_sha256(row.model_dump(mode="json"))}
        _require(row.provider_route == "pi_kimi_oauth_subscription")
        if row.outcome == "succeeded":
            _require(key in state.success_decisions and row.observed_model_counts == {"k3-256k": 1}
                     and row.provider_response_count == 1 and row.successful_decision_count == 1
                     and row.usage_complete_response_count == 1
                     and row.output_usage is not None and row.output_usage <= 1024)
            fact["decision_sha256"] = v2._json_sha256(state.success_decisions[key].model_dump(mode="json"))
            preserved_successes.append(fact)
        else:
            _require(key not in state.success_decisions and row.outcome == "nonretryable_failure"
                     and row.failure_category == "entitlement" and row.status_code == 403)
            failed_attempts.append(fact)
    _require(bool(failed_attempts))
    _require(len(preserved_successes) == sum(1 for k in state.success_decisions if k[0] in indexes))
    budget = next(row for row in state.proposal["model_budgets"] if row["requested_model"] == MODEL)
    global_remaining = state.proposal["maximum_new_physical_attempts"] - state.physical_attempts
    model_remaining = budget["maximum_new_physical_attempts"] - state.physical_by_model[MODEL]
    remaining = len(indexes) * state.per_cell - len(preserved_successes)
    _require(global_remaining >= remaining and model_remaining >= remaining)
    return {"preserved_successes": preserved_successes, "failed_attempts": failed_attempts,
            "frozen_batch": [indexes[0], 0], "remaining_logical_judgments": remaining,
            "remaining_global_physical_budget": global_remaining,
            "remaining_model_physical_budget": model_remaining}


EVENT = "kimi_official_migration_accepted"
FIELDS = {"destination_model", "maximum_inflight", "output_token_ceiling", "maximum_spend_cny", "terms"}


def transition(state: CampaignProgress, payload: dict[str, Any]) -> Callable[[], None]:
    """Record one authorization only; execution activation is a separate gate."""
    state._exact(payload, {"approval", *FIELDS})
    state._exact(payload["approval"], {"path", "sha256"})
    v2._require_sha256(payload["approval"]["sha256"], "Kimi migration approval")
    _require(
        state.kimi_migration_approval is None
        and isinstance(payload["approval"]["path"], str) and payload["approval"]["path"].startswith("/")
        and payload["destination_model"] == OFFICIAL_MODEL
        and type(payload["maximum_inflight"]) is int and payload["maximum_inflight"] == 5
        and type(payload["output_token_ceiling"]) is int and payload["output_token_ceiling"] == 1024
        and type(payload["maximum_spend_cny"]) in {int, float} and 0 < payload["maximum_spend_cny"] <= 100
        and v2._json_sha256(payload["terms"]) == v2._json_sha256(terms(state))
    )
    def accept() -> None:
        state.kimi_migration_approval = deepcopy(payload)
    return accept


REFERENCES = ('user_consent', 'health_intent', 'health_result')


def receipt_references(reference: dict[str, Any]) -> list[dict[str, Any]]:
    from ._concurrent_recovery_recheck import _checked
    document = _checked(reference)
    return [reference, *(document[k] for k in REFERENCES)]


def _evidence(reference: dict[str, Any]) -> dict[str, Any]:
    """Read immutable external qualification JSON without rewriting its bytes."""
    import json

    from . import concurrent_robustness_formal_execution as formal
    from . import concurrent_robustness_recovery as proposal

    ref = formal.FormalArtifactReference.model_validate(reference)
    fact = proposal._file_fact(ref.path)
    _require(fact['sha256'] == ref.sha256 and not cast(int, fact['mode']) & 0o222)
    value = json.loads(ref.path.read_text(), object_pairs_hook=formal._collect_object_pairs('Kimi qualification'))
    _require(isinstance(value, dict))
    return value


def validate_receipt(origins: Any, state: CampaignProgress, payload: dict[str, Any], when: Any, head: str) -> None:
    """Verify the original user consent and already-settled official qualification."""
    import hashlib
    import json

    from . import concurrent_robustness_formal_execution as formal
    from . import concurrent_robustness_recovery_task as task
    from ._concurrent_recovery_recheck import _checked
    from .decision import EngageDecision
    from .prompting import build_engagement_prompt
    from .provider_request_contract import engage_decision_json_schema

    state._exact(payload, {'approval', *FIELDS})
    approval = _checked(payload['approval'])
    state._exact(approval, {'schema_version', 'status', 'authorization_reference', 'approved_at_utc',
                            'task_plan', 'expected_head_sha256', *FIELDS, *REFERENCES})
    _require(approval['schema_version'] == 'concurrent-recovery-kimi-official-migration-approval-v1'
             and approval['status'] == 'approved' and origins.task_plan is not None
             and approval['task_plan'] == origins.handoff.model_dump(mode='json')
             and approval['expected_head_sha256'] == head
             and all(approval[k] == payload[k] for k in FIELDS))
    formal._safe_reference(approval['authorization_reference'], 'Kimi migration authorization')
    _require(bool(approval['authorization_reference']) and not approval['authorization_reference'].startswith('REPLACE-'))
    assert origins.task_plan is not None
    start = formal._parse_utc(origins.task_plan['authorization']['approved_at_utc'], 'task approval time')
    approved = formal._parse_utc(approval['approved_at_utc'], 'migration approval time')
    _require(start <= approved <= when and task._current(origins.task_plan, when))
    consent, intent, result = (_evidence(approval[k]) for k in REFERENCES)
    _require(consent['schema_version'] == 'kimi-official-migration-user-consent-v1'
             and consent['status'] == 'user_confirmed_pending_implementation' and consent['user_confirmation'] == '确认'
             and consent['plan'] == approval['task_plan'] and consent['control_head']['record_sha256'] == head
             and consent['destination_requested_model'] == consent['destination_required_observed_model'] == OFFICIAL_MODEL
             and consent['remaining_logical'] == payload['terms']['remaining_logical_judgments']
             and consent['maximum_inflight'] == payload['maximum_inflight']
             and consent['output_token_ceiling'] == payload['output_token_ceiling'])
    for consent_key, term_key in [('existing_successes', 'preserved_successes'), ('existing_failures', 'failed_attempts')]:
        observed = [{'cell_index': row['cell_index'], 'pair_schedule_position': row['pair_schedule_position'],
                     'attempt_sha256': v2._json_sha256(row['attempt'])} for row in consent[consent_key]]
        expected = [{k: row[k] for k in ('cell_index', 'pair_schedule_position', 'attempt_sha256')}
                    for row in payload['terms'][term_key]]
        def key(row: dict[str, Any]) -> tuple[int, int]:
            return row['cell_index'], row['pair_schedule_position']
        _require(sorted(observed, key=key) == sorted(expected, key=key))
    data = task._self_check_input()
    body = {'model': OFFICIAL_MODEL, 'messages': build_engagement_prompt(data), 'max_tokens': 1024,
            'reasoning_effort': 'low', 'tools': [{'type': 'function', 'function': {
                'name': 'engage_decision', 'description': 'Return one structured engagement decision.',
                'parameters': engage_decision_json_schema()['schema']}}], 'tool_choice': 'required'}
    _require(intent['requested_model'] == OFFICIAL_MODEL and intent['base_url'] == 'https://api.moonshot.cn/v1'
             and intent['input_sha256'] == data.cache_key()
             and intent['request_sha256'] == hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
             and type(intent['maximum_client_attempts']) is int and intent['maximum_client_attempts'] == 1
             and type(intent['automatic_retries']) is int and intent['automatic_retries'] == 0
             and type(intent['formal_calls']) is int and intent['formal_calls'] == 0)
    _require(result['requested_model'] == result['observed_model'] == OFFICIAL_MODEL
             and result['status'] == 'succeeded' and type(result['http_status']) is int and result['http_status'] == 200
             and type(result['client_attempts']) is int and result['client_attempts'] == 1
             and type(result['automatic_retries']) is int and result['automatic_retries'] == 0
             and type(result['formal_calls']) is int and result['formal_calls'] == 0
             and result['finish_reason'] == 'tool_calls')
    usage = result['usage']
    _require(all(type(usage[k]) is int and usage[k] >= 0 for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
             and usage['total_tokens'] == usage['prompt_tokens'] + usage['completion_tokens']
             and usage['completion_tokens'] <= 1024)
    EngageDecision.model_validate(result['decision'])
    transition(state, payload)


def activate(state: CampaignProgress, payload: dict[str, Any]) -> Callable[[], None]:
    """Activate only the previously admitted, unchanged drained migration."""
    state._exact(payload, {"approval"})
    grant = state.kimi_migration_approval
    _require(not state.kimi_migration_active and grant is not None)
    assert grant is not None
    _require(payload["approval"] == grant["approval"]
             and v2._json_sha256(terms(state)) == v2._json_sha256(grant["terms"]))
    def apply() -> None:
        state.kimi_migration_active = True
        state.parallel_active_batch = tuple(grant["terms"]["frozen_batch"])
        state.model_stage_complete = False
        state.status = "ready"
    return apply


def validate_dispatch(state: CampaignProgress, key: tuple[int, int]) -> None:
    """No migration retry exists beyond the exact admitted old subscription failure."""
    grant = state.kimi_migration_approval
    _require(state.kimi_migration_active and grant is not None and state.cells[key[0]].requested_model == MODEL)
    assert grant is not None
    _require(cash_budget(state, key)["can_reserve_one"])
    _require(state.kimi_estimate_inflight is None
             and (not state.kimi_request_quotes or key in state.kimi_request_quotes))
    prior = state.attempts(key)
    if key in state.kimi_archived_unknown:
        _require(state.kimi_manual_retry_approval is not None and not prior
                 and state.next_attempt_number(key) == 2)
        return
    from ._concurrent_recovery_kimi_retry import permitted_prior
    if permitted_prior(state, key):
        return
    if prior:
        _require(len(prior) == 1 and any(
            row["cell_index"] == key[0] and row["pair_schedule_position"] == key[1]
            and row["attempt_sha256"] == v2._json_sha256(prior[0].model_dump(mode="json"))
            for row in grant["terms"]["failed_attempts"]))


def validate_attempt(state: CampaignProgress, key: tuple[int, int], attempt: v2._V2AttemptEvidence) -> None:
    _require(state.cells[key[0]].requested_model == MODEL
             and attempt.provider_route == "moonshot_official"
             and (attempt.outcome not in {"retryable_failure", "attempts_exhausted"}
                  or (state.kimi_retry_policy is not None and attempt.failure_category in {"temporary_rate_limit", "temporary_overload"}
                      and attempt.status_code in {429, 503} and attempt.provider_response_count == 0))
             and (attempt.outcome != "succeeded" or (attempt.output_usage is not None and attempt.output_usage <= 1024)))


def judgment_reference(state: CampaignProgress, key: tuple[int, int]) -> dict[str, Any] | None:
    attempts = state.new_attempts.get(key, [])
    if not attempts or attempts[-1].provider_route != "moonshot_official":
        return None
    _require(state.kimi_migration_active and state.kimi_migration_approval is not None)
    assert state.kimi_migration_approval is not None
    return state.kimi_migration_approval["approval"]


# Frozen conservative pre-dispatch reservation, not an invoice or token estimate.
# https://platform.kimi.com/docs/pricing/chat-k3.md (2026-09-11)
_RESERVE_MICRO_CNY = 1048576 * 20 + 1024 * 100


def cash_budget(state: CampaignProgress, key: tuple[int, int] | None = None) -> dict[str, Any]:
    """Account migrated Formal spend plus per-request estimated reservations.

    Pricing ignores all input-cache discounts. Historical/subscription fees are
    intentionally untouched. An incomplete official usage record retains a nonzero
    reservation and never becomes fabricated usage. Buffered estimates are not
    guaranteed price bounds. Legacy histories retain full-context reservations. The original maximum_spend_cny is not reset.
    """
    from decimal import Decimal

    grant = state.kimi_migration_approval
    _require(grant is not None)
    assert grant is not None
    spent = 0
    unpriced = 0
    from ._concurrent_recovery_request_quote import reserve
    def reservation(k: tuple[int, int]) -> int:
        quote = state.kimi_request_quotes.get(k)
        return reserve(quote) if quote is not None else _RESERVE_MICRO_CNY
    for attempt_key, attempts in state.new_attempts.items():
        for row in attempts:
            if row.provider_route != "moonshot_official":
                continue
            if (row.usage_complete_response_count == 1 and row.input_usage is not None
                    and row.output_usage is not None):
                spent += row.input_usage * 20 + row.output_usage * 100
            else:
                spent += reservation(attempt_key)
                unpriced += 1
    spent += sum(reservation(k) for k in state.kimi_archived_unknown)
    unpriced += len(state.kimi_archived_unknown)
    reserved = sum(reservation(k) for k in state.parallel_inflight) if state.kimi_migration_active else 0
    next_reserve = reservation(key) if key is not None else min(
        (reservation(k) for k in state.kimi_request_quotes if k not in state.success_decisions
         and k not in state.parallel_inflight), default=_RESERVE_MICRO_CNY)
    effective_cap = state.kimi_cash_cap_amendment or grant
    cap = int(Decimal(str(effective_cap["maximum_spend_cny"])) * 1000000)
    return {"policy": ("kimi-k3-buffered-request-estimate-v2" if state.kimi_request_quotes else "kimi-k3-full-context-reservation-v1"), "currency": "CNY",
            "maximum_micro_cny": cap, "settled_upper_micro_cny": spent,
            "unpriced_settled_requests": unpriced, "reserved_micro_cny": reserved,
            "per_request_reserve_micro_cny": next_reserve,
            "can_reserve_one": spent + reserved + next_reserve <= cap,
            "is_invoice": False, "scope": "official_migration_formal_only"}


def cash_stop(state: CampaignProgress, payload: dict[str, Any]) -> Callable[[], None]:
    state._exact(payload, {"budget", "key"} if "key" in payload else {"budget"})
    key = None
    if "key" in payload:
        _require(isinstance(payload['key'], list) and len(payload['key']) == 2)
        key = state._parallel_key(dict(zip(('cell_index', 'pair_schedule_position'), payload['key'], strict=True)))
    _require(state.kimi_migration_active and state.status == "running" and not state.has_inflight
             and not cash_budget(state, key)["can_reserve_one"] and payload["budget"] == cash_budget(state, key))
    return lambda: setattr(state, "status", "stopped")


def preflight(state: CampaignProgress, manifest: v2.ConcurrentRobustnessManifestV2, adapters: Any) -> None:
    """Exact official resources; never relax the original manifest's v2 contract."""
    from ._concurrent_recovery_parallel_runtime import ParallelAdapterPool
    from .providers.robustness import OfficialKimiDecisionAdapter

    _require(state.kimi_migration_approval is not None and manifest.execution_profile == "formal")
    cells = tuple(c for c in manifest.prompt_model_cells if c.requested_model == MODEL)
    _require(len(cells) == 4 and set(adapters) == {c.cell_id for c in cells})
    ids: set[int] = set()
    clients: set[int] = set()
    for i in range(5):
        lane_clients: set[int] = set()
        for cell in cells:
            pool = adapters[cell.cell_id]
            _require(type(pool) is ParallelAdapterPool and len(pool.lanes) == 5)
            adapter = pool.lanes[i]
            _require(type(adapter) is OfficialKimiDecisionAdapter and id(adapter) not in ids)
            assert isinstance(adapter, OfficialKimiDecisionAdapter)
            ids.add(id(adapter))
            client = adapter.client
            _require(getattr(client, "external_provider_client", False) is True
                     and getattr(client, "provider_transport", None) == "moonshot_official"
                     and getattr(client, "output_token_ceiling_enforcement", None) == "wire_only")
            lane_clients.add(id(client))
            expected = OfficialKimiDecisionAdapter(prompt_version=cell.prompt_version, client=client)
            _require(adapter.request_evidence == expected.request_evidence
                     and adapter.request_evidence["prompt_canonical_hash"] == cell.prompt_canonical_hash
                     and adapter.request_invocations == 0
                     and v2._adapter_external_request_invocations(adapter) == 0
                     and not v2._adapter_live_api_triggered(adapter))
            v2._v2_adapter_snapshot(adapter)
        _require(len(lane_clients) == 1 and not clients & lane_clients)
        clients.update(lane_clients)


def cash_cap_transition(state: CampaignProgress, payload: dict[str, Any]) -> Callable[[], None]:
    """Raise only the explicitly approved cumulative cap; never reset spend."""
    from pathlib import Path
    state._exact(payload, {'approval', 'previous_maximum_spend_cny', 'maximum_spend_cny'})
    state._exact(payload['approval'], {'path', 'sha256'})
    v2._require_sha256(payload['approval']['sha256'], 'cash cap approval')
    _require(isinstance(payload['approval']['path'], str) and Path(payload['approval']['path']).is_absolute()
             and type(payload['previous_maximum_spend_cny']) is int and payload['previous_maximum_spend_cny'] == 100
             and type(payload['maximum_spend_cny']) is int and payload['maximum_spend_cny'] == 350
             and state.kimi_cash_cap_amendment is None and state.kimi_migration_active
             and state.current_model == MODEL and not state.task_revoked and state.status == 'stopped'
             and not state.has_inflight and state.self_check_inflight is None
             and state.reservation is None and state.pending_judgment is None and state.pending_realized is None)
    budget = cash_budget(state)
    _require(budget['maximum_micro_cny'] == 100000000 and not budget['can_reserve_one'])
    _require(not any(a and a[-1].provider_route == 'moonshot_official' and a[-1].outcome != 'succeeded'
                     for a in state.new_attempts.values()))
    def apply() -> None:
        state.kimi_cash_cap_amendment = deepcopy(payload)
        state.status = 'paused'
    return apply


def validate_cash_cap_receipt(origins: Any, state: CampaignProgress, payload: dict[str, Any],
                              when: Any, previous: dict[str, Any]) -> None:
    from . import concurrent_robustness_formal_execution as formal
    from . import concurrent_robustness_recovery_task as task
    a = _evidence(payload['approval'])
    state._exact(a, {'schema_version', 'status', 'user_confirmation', 'confirmation_context', 'recorded_at_utc',
                     'plan', 'expected_head_sha256', 'previous_maximum_spend_cny', 'maximum_spend_cny',
                     'other_models_enabled', 'production_deploy_eligible'})
    _require(previous['kind'] == 'kimi_official_cash_budget_stopped'
             and a['expected_head_sha256'] == previous['record_sha256']
             and a['schema_version'] == 'kimi-cash-cap-consent-v1' and a['status'] == 'approved'
             and isinstance(a['user_confirmation'], str) and bool(a['user_confirmation'].strip())
             and isinstance(a['confirmation_context'], str) and bool(a['confirmation_context'].strip())
             and a['other_models_enabled'] is False and a['production_deploy_eligible'] is False
             and a['plan'] == origins.handoff.model_dump(mode='json')
             and origins.task_plan is not None and task._current(origins.task_plan, when)
             and all(type(a[k]) is int and a[k] == payload[k] for k in ('previous_maximum_spend_cny', 'maximum_spend_cny'))
             and formal._parse_utc(origins.task_plan['authorization']['approved_at_utc'], 'task approval')
             <= formal._parse_utc(a['recorded_at_utc'], 'cash cap approval') <= when)
    cash_cap_transition(state, payload)
