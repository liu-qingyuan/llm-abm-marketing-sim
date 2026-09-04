from __future__ import annotations

from pathlib import Path

import pytest

from llm_abm_sim.concurrent_robustness_v2 import (
    _V2_MODELS,
    _formal_model_batch_end,
    _model_progress_fields,
    _operational_progress,
)


@pytest.mark.parametrize(
    ("completed_cells", "expected_end"),
    [(0, 4), (1, 4), (3, 4), (4, 8), (7, 8), (16, 20), (19, 20), (20, 20)],
)
def test_formal_invocation_targets_only_the_current_model_batch(
    completed_cells: int,
    expected_end: int,
) -> None:
    assert _formal_model_batch_end(completed_cells) == expected_end


def test_operational_progress_names_completed_and_active_model() -> None:
    assert _model_progress_fields(0) == {
        "model_execution_policy": "model-major-serial-one-model-per-invocation-v1",
        "model_execution_order": list(_V2_MODELS),
        "completed_models": [],
        "active_model": _V2_MODELS[0],
    }
    assert _model_progress_fields(4) == {
        "model_execution_policy": "model-major-serial-one-model-per-invocation-v1",
        "model_execution_order": list(_V2_MODELS),
        "completed_models": [_V2_MODELS[0]],
        "active_model": _V2_MODELS[1],
    }
    assert _model_progress_fields(20) == {
        "model_execution_policy": "model-major-serial-one-model-per-invocation-v1",
        "model_execution_order": list(_V2_MODELS),
        "completed_models": list(_V2_MODELS),
        "active_model": None,
    }


@pytest.mark.parametrize("completed_cells", [-1, 21])
def test_model_progress_rejects_out_of_range_cell_count(completed_cells: int) -> None:
    with pytest.raises(ValueError, match="completed cell count"):
        _formal_model_batch_end(completed_cells)
    with pytest.raises(ValueError, match="completed cell count"):
        _model_progress_fields(completed_cells)


def test_operational_progress_rejects_skipping_to_a_future_model_cell(
    tmp_path: Path,
) -> None:
    root = tmp_path / "operational"
    (root / "cell-01").mkdir(parents=True)

    with pytest.raises(ValueError, match="contiguous prefix"):
        _operational_progress(root)
