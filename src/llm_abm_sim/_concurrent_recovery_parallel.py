"""Immutable approval validation for same-task, Gemini-only four-way dispatch.

The extension changes in-flight cardinality only. It does not renew task time,
reset budgets, authorize probes, release terminal stops or change frozen inputs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import concurrent_robustness_formal_execution as formal
from . import concurrent_robustness_recovery_execution as execution
from ._concurrent_recovery_campaign import RecoveryCampaignError
from ._concurrent_recovery_progress import CampaignProgress
from ._concurrent_recovery_recheck import _checked

EVENT = "parallel_execution_accepted"
FIELDS = {"requested_model", "maximum_inflight", "stop_after_model"}


def validate_receipt(
    origins: execution._Origins, state: CampaignProgress, payload: dict[str, Any], when: datetime, head: str
) -> None:
    from . import concurrent_robustness_recovery_task as task

    if set(payload) != {"approval", *FIELDS}:
        raise RecoveryCampaignError("Parallel receipt fields are crossed")
    approval = _checked(payload["approval"])
    expected = {
        "schema_version",
        "status",
        "authorization_reference",
        "approved_at_utc",
        "task_plan",
        "paused_head_sha256",
        *FIELDS,
    }
    if (
        set(approval) != expected
        or approval["schema_version"] != "concurrent-recovery-parallel-approval-v1"
        or approval["status"] != "approved"
        or origins.task_plan is None
        or approval["task_plan"] != origins.handoff.model_dump(mode="json")
        or approval["paused_head_sha256"] != head
        or not task._current(origins.task_plan, when)
    ):
        raise RecoveryCampaignError("Parallel approval differs from its original paused task")
    reference = approval["authorization_reference"]
    formal._safe_reference(reference, "parallel approval reference")
    if not reference or reference.startswith("REPLACE-"):
        raise RecoveryCampaignError("Parallel approval requires an explicit reference")
    approved = formal._parse_utc(approval["approved_at_utc"], "parallel approval time")
    task_approved = formal._parse_utc(origins.task_plan["authorization"]["approved_at_utc"], "task approval time")
    if not task_approved <= approved <= when or any(approval[k] != payload[k] for k in FIELDS):
        raise RecoveryCampaignError("Parallel approval time or dispatch scope is crossed")
    state.transition(EVENT, payload)


def receipt_references(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    approval = _checked(payload["approval"])
    return payload["approval"], approval["task_plan"]
