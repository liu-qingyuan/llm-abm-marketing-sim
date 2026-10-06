"""Partial delivery derived from actually executed paths; not a 2800-path completion claim."""

import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_evidence import _estimate, t_quantile

ROOT = Path(__file__).resolve().parent
OLD = Path("/Users/liuqingyuan/work/llm-abm-marketing-sim/runs")


def run():
    source = ROOT / "ready-formal-paths"
    manifest = bank.read_json(source / "partial-manifest.json")
    if len(manifest["completed_verified_paths"]) != 2700:
        raise ValueError("scope path closure incomplete")
    dest = ROOT / "ready-formal-report"
    if dest.exists():
        raise ValueError("new report required")
    dest.mkdir()
    rows = []
    groups = defaultdict(list)
    for relative, digest in manifest["completed_verified_paths"].items():
        path = source / relative
        bank.bound(path, digest, "executed scope path")
        doc = bank.read_json(path)
        if doc["path_sha256"] != bank.fingerprint(doc["path"]):
            raise ValueError("path payload hash differs")
        identity = doc["identity"]
        study = identity["study"]
        label = identity["configuration"]
        seed = identity["seed"]
        oldpath = (
            (OLD / "gpt-p0-dynamic-parameters-20260917-formal-01" / f"{label}-s{seed}.json")
            if study == "parameters"
            else (OLD / "gpt-p0-index-sensitivity-20260920-formal-01/paths" / f"{label}-s{seed}.json")
        )
        prior = bank.read_json(oldpath)
        if prior["path_sha256"] != bank.fingerprint(prior["path"]):
            raise ValueError("old path hash differs")
        for message in ["message_1", "message_2", "message_3", "all"]:
            a = [r for r in prior["path"]["terminals"] if message == "all" or r["message_id"] == message]
            b = [r for r in doc["path"]["terminals"] if message == "all" or r["message_id"] == message]
            ca = Counter(r["realized_action"] for r in a)
            cb = Counter(r["realized_action"] for r in b)
            ea = sum(ca[k] for k in ["like", "comment", "share"])
            eb = sum(cb[k] for k in ["like", "comment", "share"])
            record = {
                "study": study,
                "configuration": label,
                "seed": seed,
                "message": message,
                "exposures": len(b),
                "old_engagement": ea,
                "new_engagement": eb,
                "old_rate": ea / len(a),
                "new_rate": eb / len(b),
                "difference_pp": 100 * (eb / len(b) - ea / len(a)),
            }
            for action in ["like", "comment", "share", "ignore"]:
                record["old_" + action] = ca[action]
                record["new_" + action] = cb[action]
            rows.append(record)
            groups[study, label, message].append(record)

    def write(name, data):
        with (dest / name).open("w", newline="") as h:
            w = csv.DictWriter(h, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)

    write("completed-scope-old-new-path-metrics.csv", rows)
    critical = t_quantile(0.975)
    summary = []
    for (study, label, message), values in sorted(groups.items()):
        if len(values) != 100:
            raise ValueError("seed coverage differs")
        deltas = [r["new_rate"] - r["old_rate"] for r in values]
        summary.append(
            {
                "study": study,
                "configuration": label,
                "message": message,
                "seeds": 100,
                "old_rate_mean": statistics.mean(r["old_rate"] for r in values),
                "new_rate_mean": statistics.mean(r["new_rate"] for r in values),
                **{"delta_" + k: v for k, v in _estimate(deltas, critical).items()},
            }
        )
    write("completed-scope-old-new-estimates.csv", summary)
    for seed in range(2026091700, 2026091800):
        a = bank.read_json(source / f"index/local_weights_fixed-s{seed}.json")["path"]
        b = bank.read_json(source / f"index/local_weights_rebuilt-s{seed}.json")["path"]
        if a != b:
            raise ValueError("Local fixed/rebuilt differ")
        x = bank.read_json(source / f"index/baseline-s{seed}.json")["path"]
        y = bank.read_json(source / f"parameters/w0-h3-s{seed}.json")["path"]
        if x != y:
            raise ValueError("shared baseline differs")
    lines = [
        "# 已闭合范围的阶段报告",
        "",
        "整体仍为partial，目标保持2800路径。本报告不声称两项研究已全部完成。",
        "参数研究2100路径和指标六臂600路径已实际运行并独立逐批核验，共4860000曝光、81000 barriers；本次重开核对所有2700路径hash、payload及100seed覆盖。",
        "Local权重fixed/rebuilt全部100条payload实际相同；参数w0-h3与指标baseline100条实际相同。",
        "最后local_p99_rebuilt臂仍缺3条unknown判断，100条路径未执行；没有用模拟或旧证明替代。",
        "新旧差异包括网络、样本、指标、模型服务时点，非纯指标因果效应。下表仅完成范围的总互动率100seed均值；ordinary df99配对区间见CSV，正式完整报告仍待全部闭合。",
        "",
        "| 研究/配置 | 旧率 | 新率 | 差pp |",
        "|---|---:|---:|---:|",
    ]
    for r in summary:
        if r["message"] == "all":
            lines.append(
                f"| {r['study']}/{r['configuration']} | {100 * r['old_rate_mean']:.3f}% | {100 * r['new_rate_mean']:.3f}% | {100 * r['delta_mean']:+.3f} |"
            )
    (dest / "REPORT.md").write_text("\n".join(lines) + "\n")
    bank.write_json(
        dest / "evidence.json",
        {
            "overall_status": "partial",
            "completed_scope_paths": 2700,
            "unexecuted_paths": 100,
            "scope_exposures": 4860000,
            "scope_barriers": 81000,
            "source_manifest_sha256": bank.file_hash(source / "partial-manifest.json"),
            "local_fixed_rebuilt_100_payloads_equal": True,
            "shared_baseline_100_payloads_equal": True,
            "files": {f.name: bank.file_hash(f) for f in dest.iterdir() if f.is_file()},
        },
    )
    print("Partial delivery reopened: 2700 real paths, 4860000 exposures; 100 paths remain unexecuted")


if __name__ == "__main__":
    run()
