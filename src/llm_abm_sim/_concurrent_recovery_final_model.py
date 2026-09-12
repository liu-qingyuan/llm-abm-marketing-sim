"""One explicit final-model continuation; original five-model evidence is immutable."""
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

EVENT = "final_model_continuation_accepted"
MODEL = "openai-codex/gpt-5.6-sol"
EXCLUDED = "gemini-3.8-flash-high"
FIELDS = {"requested_model", "excluded_model", "stop_after_model"}


def _require(value: bool) -> None:
    if not value:
        raise RecoveryCampaignError("Final-model continuation differs from its completed original campaign")


def transition(state: CampaignProgress, payload: dict[str, Any]) -> Callable[[], None]:
    state._exact(payload, {"approval", *FIELDS})
    state._exact(payload["approval"], {"path", "sha256"})
    v2._require_sha256(payload["approval"]["sha256"], "final-model approval")
    _require(payload["requested_model"] == MODEL and payload["excluded_model"] == EXCLUDED
             and payload["stop_after_model"] is True
             and isinstance(payload["approval"]["path"], str) and payload["approval"]["path"].startswith("/"))
    _require(state.final_model_continuation is None and state.status == "model_complete"
             and state.model_stage_complete and state.kimi_migration_active
             and state.current_model == "kimi-coding/k3-256k"
             and state.task_plan is not None and not state.task_revoked and not state.has_inflight
             and not state.parallel_unknown and state.self_check_inflight is None
             and state.reservation is None and state.pending_judgment is None and state.pending_realized is None
             and state.parallel_active_batch is None and state.quota_retry_pending is None)
    _require(len(state.cells) == 20 and state.per_cell == 1800
             and {c.requested_model for c in state.cells} == {
                 "deepseek-v4-flash", "gemini-3.1-pro", EXCLUDED, "kimi-coding/k3-256k", MODEL})
    for i, cell in enumerate(state.cells):
        if cell.requested_model in {MODEL, EXCLUDED}:
            _require(state.prefix[i] == 0 and cell.requested_model not in state.self_check_intents
                     and cell.requested_model not in state.self_checks
                     and not any(k[0] == i for k in state.new_attempts))
        else:
            _require(state.prefix[i] == state.per_cell)
            inherited = next((c for c in state.proposal["inherited_cells"] if c["cell_index"] == i), None)
            inherited_steps = len(inherited["inherited_pairs"]) // 60 if inherited is not None else 0
            for step in range(inherited_steps, 30):
                _require(any(ci == i and st == step for _, ci, st in state.batch_commits))
    cap = next(r["maximum_new_physical_attempts"] for r in state.proposal["model_budgets"]
               if r["requested_model"] == MODEL)
    _require(state.physical_attempts < state.proposal["maximum_new_physical_attempts"]
             and state.physical_by_model[MODEL] < cap)

    def accept() -> None:
        state.final_model_continuation = deepcopy(payload)
        state.kimi_migration_active = False
        state.model_stage_complete = False
        state.status = "ready"
    return accept


def validate_receipt(origins: _Origins, state: CampaignProgress, payload: dict[str, Any],
                     when: datetime, head: str) -> None:
    from . import concurrent_robustness_recovery_task as task
    approval = _checked(payload["approval"])
    state._exact(approval, {"schema_version", "status", "authorization_reference", "approved_at_utc",
                           "task_plan", "completed_head_sha256", *FIELDS})
    _require(origins.task_plan is not None
             and approval["schema_version"] == "concurrent-recovery-final-model-approval-v1"
             and approval["status"] == "approved"
             and approval["task_plan"] == origins.handoff.model_dump(mode="json")
             and approval["completed_head_sha256"] == head
             and all(approval[k] == payload[k] for k in FIELDS))
    assert origins.task_plan is not None
    _require(task._current(origins.task_plan, when))
    reference = approval["authorization_reference"]
    formal._safe_reference(reference, "final-model authorization")
    _require(bool(reference) and not reference.startswith("REPLACE-"))
    approved = formal._parse_utc(approval["approved_at_utc"], "final-model approval time")
    start = formal._parse_utc(origins.task_plan["authorization"]["approved_at_utc"], "task approval time")
    _require(start <= approved <= when)
    transition(state, payload)


PARALLEL_EVENT = 'final_model_parallel_accepted'
PARALLEL_FIELDS = {'requested_model', 'maximum_inflight', 'stop_after_model'}


def parallel_transition(state: CampaignProgress, payload: dict[str, Any]) -> Callable[[], None]:
    state._exact(payload, {'approval', *PARALLEL_FIELDS})
    state._exact(payload['approval'], {'path', 'sha256'})
    v2._require_sha256(payload['approval']['sha256'], 'final-model parallel approval')
    check = state.effective_self_check(MODEL)
    _require(state.final_model_continuation is not None and state.final_model_parallel is None
             and state.current_model == MODEL and state.status == 'paused' and bool(state.epochs)
             and state.epochs[-1]['requested_model'] == MODEL and state.task_plan is not None
             and not state.task_revoked and not state.has_inflight and not state.parallel_unknown
             and state.self_check_inflight is None and state.reservation is None
             and state.pending_judgment is None and state.pending_realized is None
             and state.parallel_active_batch is None and state.quota_retry_pending is None
             and check is not None and check['attempt']['outcome'] == 'succeeded'
             and payload['requested_model'] == MODEL and type(payload['maximum_inflight']) is int
             and payload['maximum_inflight'] == 5 and payload['stop_after_model'] is True
             and isinstance(payload['approval']['path'], str) and payload['approval']['path'].startswith('/'))
    _require(all(n % 60 == 0 for n in state.prefix)
             and state.physical_attempts < state.proposal['maximum_new_physical_attempts'])
    cap = next(r['maximum_new_physical_attempts'] for r in state.proposal['model_budgets']
               if r['requested_model'] == MODEL)
    _require(state.physical_by_model[MODEL] < cap)
    for i, cell in enumerate(state.cells):
        if cell.requested_model == MODEL:
            for step in range(state.prefix[i] // 60):
                _require(any(ci == i and st == step for _, ci, st in state.batch_commits))
    return lambda: setattr(state, 'final_model_parallel', deepcopy(payload))


def validate_parallel_receipt(origins: _Origins, state: CampaignProgress, payload: dict[str, Any],
                              when: datetime, head: str) -> None:
    from . import concurrent_robustness_recovery_task as task
    approval = _checked(payload['approval'])
    state._exact(approval, {'schema_version', 'status', 'authorization_reference', 'approved_at_utc',
                           'task_plan', 'paused_head_sha256', *PARALLEL_FIELDS})
    _require(origins.task_plan is not None
             and approval['schema_version'] == 'concurrent-recovery-final-model-parallel-approval-v1'
             and approval['status'] == 'approved'
             and approval['task_plan'] == origins.handoff.model_dump(mode='json')
             and approval['paused_head_sha256'] == head
             and all(approval[k] == payload[k] for k in PARALLEL_FIELDS))
    assert origins.task_plan is not None
    _require(task._current(origins.task_plan, when))
    reference = approval['authorization_reference']
    formal._safe_reference(reference, 'final-model parallel authorization')
    _require(bool(reference) and not reference.startswith('REPLACE-'))
    approved = formal._parse_utc(approval['approved_at_utc'], 'parallel approval time')
    start = formal._parse_utc(origins.task_plan['authorization']['approved_at_utc'], 'task approval time')
    _require(start <= approved <= when)
    parallel_transition(state, payload)
