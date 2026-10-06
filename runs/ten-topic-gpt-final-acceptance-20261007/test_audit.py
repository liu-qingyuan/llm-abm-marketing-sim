import importlib.util
import math
from pathlib import Path

import pytest

p = Path(__file__).with_name("audit.py")
spec = importlib.util.spec_from_file_location("acceptance_audit", p)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def test_independent_student_quantile_and_intervals():
    assert math.isclose(a.tq(0.975), 1.9842169515, abs_tol=2e-9)
    e = a.estimate(list(range(100)), a.tq(0.975))
    assert e["mean"] == 49.5 and math.isclose(e["sd"], math.sqrt(100 * 101 / 12), abs_tol=1e-12)
    assert e["lower"] < e["mean"] < e["upper"]


def test_checksum_mutation_fails():
    body = {"sequence": 0, "previous_sha256": "fixture", "kind": "intent", "payload": {"key": "A"}}
    original = a.fp(body)
    body["payload"]["key"] = "B"
    assert a.fp(body) != original
    with pytest.raises(ValueError):
        a.require(False, "mutated_fixture_should_fail")


def test_seed_input_changes_hash_not_cross_user_alias():
    assert a.fp(["draw", "anchor", 1, "A", "M"]) != a.fp(["draw", "anchor", 1, "B", "M"])
    assert a.key({"user_id": "A", "message_id": "M", "client_condition_sha256": "same"}) != a.key(
        {"user_id": "B", "message_id": "M", "client_condition_sha256": "same"}
    )
