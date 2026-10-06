from pathlib import Path

import bank_union
import live_study
import pytest

from llm_abm_sim import _parameter_judgment_bank as bank

ROOT = Path(__file__).resolve().parent


def test_real_stopped_stage_prefix_and_unattempted_partition():
    prep, accepted, unknown, intents, settlements, peak = bank_union.stage_facts(ROOT / "formal-bank", True)
    assert len(accepted) == 2067 and len(unknown) == 1 and len(intents) == len(settlements) == 2069
    assert peak == 5
    child = bank.read_json(ROOT / "unattempted-stage-01/preparation.json")
    old = live_study.frozen.read_rows(ROOT / "formal-bank/accepted-bank.jsonl")
    assert live_study.frozen.read_rows(ROOT / "unattempted-stage-01/accepted-bank.jsonl") == old + list(
        accepted.values()
    )
    missing = live_study.frozen.read_rows(ROOT / "unattempted-stage-01/missing-pairs.jsonl")
    attempted = {r["pair_key"] for r in intents if r["purpose"] == "judgment"}
    assert len(missing) == 5144 and not {live_study.key(r) for r in missing} & attempted
    assert child["overall_universe"] == 17520 and child["universe"] == 17519


def test_stopped_stage_never_passes_complete_stage_contract():
    with pytest.raises(AssertionError):
        bank_union.stage_facts(ROOT / "formal-bank", False)


def test_missing_resolution_never_publishes_final_bank(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        bank_union.validate(tmp_path)
    assert not (tmp_path / "final-bank").exists()
