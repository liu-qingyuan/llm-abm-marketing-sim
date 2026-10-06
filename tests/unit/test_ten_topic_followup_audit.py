import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts/audit_ten_topic_followups.py"
    spec = importlib.util.spec_from_file_location("offline_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matching_prompt_is_not_cross_user_judgment_reuse():
    audit = _module()
    first = {"user_id": "A", "message_id": "M1", "client_condition_sha256": "same-prompt"}
    other = {**first, "user_id": "B"}
    assert audit._pair_input_key(first) != audit._pair_input_key(other)
    assert audit._pair_input_key(first) != audit._pair_input_key({**first, "message_id": "M2"})
    assert audit._pair_input_key(first) == audit._pair_input_key({**first, "arm": "another_arm"})


def test_missing_inventory_deduplicates_seeds_and_arms_not_pairs_or_models():
    audit = _module()
    row = {"model": "GPT", "template": "P0", "user_id": "A", "message_id": "M1", "client_identity": "same"}
    rows = [row, {**row, "seed": 2}, {**row, "arm": "local_fixed"}, {**row, "user_id": "B"}, {**row, "model": "Kimi"}]
    assert len({audit._missing_identity(r) for r in rows}) == 3
