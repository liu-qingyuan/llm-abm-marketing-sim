"""Unit fixtures only; these tests do not produce Formal research artifacts."""

import copy
import json
from pathlib import Path

import offline_path_engine as engine
import pytest

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_study import draw
from llm_abm_sim.concurrent_message_experiment import (
    ConcurrentMessageExperimentConfig,
    _prepare_full_pool_concurrent_runtime_inputs,
)
from tests.integration.test_full_pool_segmented_multibatch import _dataset


def fixture(tmp_path):
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=_dataset(tmp_path),
        sample_size=7,
        horizon=2,
        delivery_capacity=3,
        configuration_profile="validation",
    )
    prepared = _prepare_full_pool_concurrent_runtime_inputs(config, seed_top_k_per_proxy=1)
    condition = json.loads((Path(__file__).parent / "preflight-final/preflight.json").read_text())["request_condition"]
    records = []
    for index, user in enumerate(prepared.cohort.sample_user_ids):
        for msg in config.messages:
            data = engine.decision_input(config, prepared, condition, user, msg.message_id)
            mh, ch = bank.client_identity(data, condition)
            records.append(
                {
                    "user_id": user,
                    "message_id": msg.message_id,
                    "client_messages_sha256": mh,
                    "client_condition_sha256": ch,
                    "source": "UNIT_TEST_FIXTURE_ONLY",
                    "decision": {
                        "engage": True,
                        "probability": 0.65,
                        "confidence": 0.9,
                        "reason": "UNIT_TEST_FIXTURE_ONLY",
                        "action": ["like", "comment", "share"][index % 3],
                    },
                }
            )
    return config, prepared, condition, records


@pytest.mark.parametrize("weights,saturation", [((0.5, 0.3, 0.2), 3), ((0.65, 0.15, 0.2), 1), ((0.5, 0.15, 0.35), 6)])
def test_kernel_and_independent_verifier(tmp_path, weights, saturation):
    config, prepared, condition, records = fixture(tmp_path)
    args = dict(anchor="original-fixed-anchor", seed=2026091700, weights=weights, saturation=saturation)
    result = engine.execute(config, prepared, condition, records, **args)
    assert engine.verify(result, config, prepared, condition, records, **args) == {
        "exposures": 18,
        "barriers": 2,
        "provider_calls": 0,
    }
    bad = copy.deepcopy(result)
    bad["barriers"][0]["frozen_positive_user_ids"] = ["impossible-before-first-batch"]
    with pytest.raises(ValueError):
        engine.verify(bad, config, prepared, condition, records, **args)
    bad = copy.deepcopy(result)
    bad["terminals"][0]["uniform_draw"] = 0.123
    with pytest.raises(ValueError):
        engine.verify(bad, config, prepared, condition, records, **args)


def test_missing_candidate_fails_before_kernel_even_if_unexposed(tmp_path, monkeypatch):
    config, prepared, condition, records = fixture(tmp_path)
    monkeypatch.setattr(
        engine._ConcurrentRuntimeKernel, "fixed_judgment_path", lambda **kwargs: pytest.fail("kernel must not run")
    )
    with pytest.raises(ValueError, match="complete candidate judgment bank"):
        engine.execute(
            config, prepared, condition, records[:-1], anchor="old", seed=1, weights=(0.5, 0.3, 0.2), saturation=3
        )


def test_legacy_anchor_not_new_bank_or_directory_identity():
    anchor = json.loads((Path(__file__).parent / "preflight-final/preflight.json").read_text())["draw_anchor"]
    for seed in range(2026091700, 2026091800):
        assert engine.anchored_draw(anchor, seed, "sample-user", "message_1") == draw(
            anchor, seed, "sample-user", "message_1"
        )
        assert engine.anchored_draw(anchor, seed, "sample-user", "message_1") != engine.anchored_draw(
            "new-bank-hash", seed, "sample-user", "message_1"
        )


def test_prevalidated_cache_has_identical_path_and_independent_rejection(tmp_path):
    import fast_paths

    config, prepared, condition, records = fixture(tmp_path)
    campaign = fast_paths.Campaign(config, prepared, condition, records)
    for seed in range(2026091700, 2026091710):
        args = dict(anchor="original-fixed-anchor", seed=seed, weights=(0.5, 0.3, 0.2), saturation=3)
        path = campaign.execute(**args)
        assert path == engine.execute(config, prepared, condition, records, **args)
        assert campaign.verify(path, **args)
        bad = copy.deepcopy(path)
        bad["terminals"][0]["ranking_score"] += 0.001
        with pytest.raises(ValueError):
            campaign.verify(bad, **args)
