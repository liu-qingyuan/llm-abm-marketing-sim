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
