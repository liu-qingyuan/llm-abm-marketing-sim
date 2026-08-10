from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_concurrent_robustness_formal_cell.py"
_SPEC = importlib.util.spec_from_file_location("concurrent_robustness_formal_cell", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
CellBudgetGuard = _MODULE.CellBudgetGuard


def test_cell_budget_guard_reserves_retry_cap_and_closes_terminal() -> None:
    guard = CellBudgetGuard(logical_cap=2, physical_cap=6, max_retries=2)

    guard.before({"pair_id": "u1:message_1:0"})
    guard.after({"pair_id": "u1:message_1:0", "request_invocations": 1})
    guard.before({"pair_id": "u2:message_1:0"})
    guard.after({"pair_id": "u2:message_1:0", "request_invocations": 3})

    assert guard.logical_judgments == 2
    assert guard.physical_attempts == 4
    with pytest.raises(RuntimeError, match="exceed"):
        guard.before({"pair_id": "u3:message_1:0"})


def test_cell_budget_guard_rejects_crossed_terminal_identity() -> None:
    guard = CellBudgetGuard(logical_cap=1, physical_cap=3, max_retries=2)
    guard.before({"pair_id": "u1:message_1:0"})

    with pytest.raises(RuntimeError, match="crossed"):
        guard.after({"pair_id": "u2:message_1:0", "request_invocations": 1})
