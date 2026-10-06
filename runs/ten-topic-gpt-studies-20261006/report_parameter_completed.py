"""Original parameter statistical protocol over actually completed 2100 paths."""

import csv
import statistics
from pathlib import Path

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_evidence import _estimate, t_quantile
from llm_abm_sim._parameter_study import CONFIGURATIONS, SEEDS

ROOT = Path(__file__).resolve().parent
p = ROOT / "ready-formal-report"
data = {}
with (p / "completed-scope-old-new-path-metrics.csv").open() as h:
    for r in csv.DictReader(h):
        if r["study"] == "parameters":
            data[r["configuration"], int(r["seed"]), r["message"]] = r
assert len(data) == 2100 * 4
ordinary = t_quantile(0.975)
critical = t_quantile(1 - 0.05 / (2 * 123))
rates = []
contrasts = []
for label, weights, threshold in CONFIGURATIONS:
    for message in ["message_1", "message_2", "message_3"]:
        values = [float(data[label, seed, message]["new_rate"]) for seed in SEEDS]
        old = [float(data[label, seed, message]["old_rate"]) for seed in SEEDS]
        rates.append(
            {
                "configuration": label,
                "network_weight": weights[0],
                "feedback_weight": weights[1],
                "content_weight": weights[2],
                "threshold": threshold,
                "message": message,
                "old_rate_mean": statistics.mean(old),
                "seed_count": 100,
                **_estimate(values, ordinary),
            }
        )
    for a, b in [("message_1", "message_2"), ("message_1", "message_3"), ("message_2", "message_3")]:
        ds = [float(data[label, s, a]["new_rate"]) - float(data[label, s, b]["new_rate"]) for s in SEEDS]
        delta = [
            d - (float(data["w0-h3", s, a]["new_rate"]) - float(data["w0-h3", s, b]["new_rate"]))
            for d, s in zip(ds, SEEDS, strict=True)
        ]
        difference = _estimate(ds, critical)
        effect = _estimate(delta, critical)
        contrasts.append(
            {
                "configuration": label,
                "contrast": a + "-" + b,
                **{"difference_" + k: v for k, v in difference.items()},
                **{"delta_" + k: v for k, v in effect.items()},
                "difference_ordinary_lower": statistics.mean(ds) - ordinary * difference["mcse"],
                "difference_ordinary_upper": statistics.mean(ds) + ordinary * difference["mcse"],
                "delta_ordinary_lower": statistics.mean(delta) - ordinary * effect["mcse"],
                "delta_ordinary_upper": statistics.mean(delta) + ordinary * effect["mcse"],
                "epsilon": 0.02,
                "mc_halfwidth_target": 0.005,
                "mc_precision_met": ordinary * effect["mcse"] <= 0.005,
                "direction": "positive"
                if difference["lower"] > 0.02
                else "negative"
                if difference["upper"] < -0.02
                else "near_zero"
                if difference["lower"] >= -0.02 and difference["upper"] <= 0.02
                else "undetermined",
                "amplitude": "baseline"
                if label == "w0-h3"
                else "equivalent_in_tested_range"
                if effect["lower"] >= -0.02 and effect["upper"] <= 0.02
                else "sensitive"
                if effect["lower"] > 0.02 or effect["upper"] < -0.02
                else "undetermined",
            }
        )
for name, rows in [("parameter-rates.csv", rates), ("parameter-message-contrasts.csv", contrasts)]:
    target = p / name
    if target.exists():
        raise ValueError("do not overwrite previous statistics")
    with target.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
bank.write_json(
    p / "parameter-statistical-protocol.json",
    {
        "parameter_paths": 2100,
        "n_behavior_seeds": 100,
        "rate_cells": 63,
        "message_contrasts": 63,
        "df": 99,
        "bonferroni_family": 123,
        "ordinary_t": ordinary,
        "adjusted_t": critical,
        "epsilon": 0.02,
        "mc_halfwidth_target": 0.005,
        "source_metrics_sha256": bank.file_hash(p / "completed-scope-old-new-path-metrics.csv"),
        "parameter_artifact_hashes": {
            name: bank.file_hash(p / name) for name in ["parameter-rates.csv", "parameter-message-contrasts.csv"]
        },
        "overall_two_study_status": "partial_missing_three_Local_p99_rebuilt_judgments",
    },
)
print(
    "Original parameter statistics executed: 2100 paths; 63 rates/63 message contrasts; family123; overall objective still partial"
)
