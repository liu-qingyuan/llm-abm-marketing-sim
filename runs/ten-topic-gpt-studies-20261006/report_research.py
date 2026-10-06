"""Reopen every real path; independently verify and derive all tables from terminals."""

import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import fast_paths
import live_study
import verify_collection

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_collection import _publish
from llm_abm_sim._parameter_evidence import _estimate, t_quantile
from llm_abm_sim._parameter_study import CONFIGURATIONS, SEEDS
from llm_abm_sim.concurrent_message_experiment import _prepare_concurrent_runtime_inputs

ROOT = Path(__file__).resolve().parent
OLD = Path("/Users/liuqingyuan/work/llm-abm-marketing-sim/runs")
METRICS = ("like", "comment", "share", "engagement", "engagement_rate")


def metrics(rows):
    c = Counter(r["realized_action"] for r in rows)
    e = sum(c[a] for a in ("like", "comment", "share"))
    return {
        "exposures": len(rows),
        "like": c["like"],
        "comment": c["comment"],
        "share": c["share"],
        "ignore": c["ignore"],
        "engagement": e,
        "engagement_rate": e / len(rows),
    }


def csv_write(path, rows):
    with path.open("w", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def exposure_delta(a, b):
    a = [(r["user_id"], r["message_id"]) for r in a]
    b = [(r["user_id"], r["message_id"]) for r in b]
    sa, sb = set(a), set(b)
    pa = {r: i for i, r in enumerate(a)}
    pb = {r: i for i, r in enumerate(b)}
    common = sa & sb
    return {
        "pair_added": len(sb - sa),
        "pair_removed": len(sa - sb),
        "pair_jaccard": len(common) / len(sa | sb),
        "position_mismatches": sum(x != y for x, y in zip(a, b, strict=True)),
        "common_position_shift": statistics.mean(abs(pa[k] - pb[k]) for k in common) if common else 0.0,
    }


def run():
    dest = ROOT / "formal-report"
    if dest.exists():
        raise ValueError("new report output required")
    manifest = bank.read_json(ROOT / "formal-paths/manifest.json")
    expected = {f"parameters/{label}-s{seed}.json" for label, _, _ in CONFIGURATIONS for seed in SEEDS}
    expected |= {f"index/{arm}-s{seed}.json" for arm in live_study.ARMS for seed in SEEDS}
    if set(manifest["paths"]) != expected or manifest["status"] != "complete_verified":
        raise ValueError("path matrix incomplete")
    closure = verify_collection.validate(ROOT / "formal-bank")
    prep = bank.read_json(ROOT / "formal-bank/preparation.json")
    if closure["bank_sha256"] != manifest["bank_sha256"] or prep["draw_anchor"] != manifest["draw_anchor"]:
        raise ValueError("bank/draw identity differs")
    cfg, _, source = bank._inputs(bank.read_json(Path(prep["audit"]["path"])))
    cfg = cfg.model_copy(update={"network_scope": "final_collected_topics"})
    base = _prepare_concurrent_runtime_inputs(cfg)
    records = live_study.frozen.read_rows(ROOT / "formal-bank/closed-bank.jsonl")
    campaigns = {}
    data = {}
    old_data = {}
    path_rows = []
    exposure_rows = []
    curve_groups = defaultdict(list)
    dest.mkdir()
    curve_path = dest / "old-new-cumulative-curves.csv"
    curve_fields = [
        "study",
        "configuration",
        "seed",
        "message",
        "batch",
        "exposures",
        "old_like",
        "new_like",
        "old_comment",
        "new_comment",
        "old_share",
        "new_share",
        "old_ignore",
        "new_ignore",
        "old_engagement",
        "new_engagement",
        "old_rate",
        "new_rate",
    ]
    with curve_path.open("w", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=curve_fields)
        writer.writeheader()
        for study in ["parameters", "index"]:
            runs = CONFIGURATIONS if study == "parameters" else [(arm, (0.5, 0.3, 0.2), 3) for arm in live_study.ARMS]
            for label, weights, saturation in runs:
                arm = "baseline" if study == "parameters" else label
                if arm not in campaigns:
                    prepared, _ = live_study.arm_inputs(cfg, base, arm)
                    campaigns[arm] = fast_paths.Campaign(cfg, prepared, prep["request_condition"], records)
                for seed in SEEDS:
                    relative = f"{study}/{label}-s{seed}.json"
                    path = ROOT / "formal-paths" / relative
                    bank.bound(path, manifest["paths"][relative], "new persisted path")
                    doc = bank.read_json(path)
                    if doc["path_sha256"] != bank.fingerprint(doc["path"]):
                        raise ValueError("path payload hash differs")
                    campaigns[arm].verify(doc["path"], prep["draw_anchor"], seed, tuple(weights), saturation)
                    oldpath = (
                        (OLD / "gpt-p0-dynamic-parameters-20260917-formal-01" / f"{label}-s{seed}.json")
                        if study == "parameters"
                        else (OLD / "gpt-p0-index-sensitivity-20260920-formal-01/paths" / f"{label}-s{seed}.json")
                    )
                    prior = bank.read_json(oldpath)
                    if prior["path_sha256"] != bank.fingerprint(prior["path"]):
                        raise ValueError("old persisted path payload differs")
                    a, b = prior["path"]["terminals"], doc["path"]["terminals"]
                    exposure_rows.append({"study": study, "configuration": label, "seed": seed, **exposure_delta(a, b)})
                    for message in ["message_1", "message_2", "message_3", "all"]:
                        before = [r for r in a if message == "all" or r["message_id"] == message]
                        after = [r for r in b if message == "all" or r["message_id"] == message]
                        old = metrics(before)
                        new = metrics(after)
                        key = study, label, seed, message
                        data[key] = new
                        old_data[key] = old
                        path_rows.append(
                            {
                                "study": study,
                                "configuration": label,
                                "seed": seed,
                                "message": message,
                                **{f"old_{k}": v for k, v in old.items()},
                                **{f"new_{k}": v for k, v in new.items()},
                                "engagement_delta_pp": 100 * (new["engagement_rate"] - old["engagement_rate"]),
                            }
                        )
                        ca = Counter()
                        cb = Counter()
                        for batch in range(30):
                            ca.update(r["realized_action"] for r in before if r["time_step"] == batch)
                            cb.update(r["realized_action"] for r in after if r["time_step"] == batch)
                            exposures = (60 if message == "all" else 20) * (batch + 1)
                            ea = sum(ca[x] for x in ["like", "comment", "share"])
                            eb = sum(cb[x] for x in ["like", "comment", "share"])
                            row = {
                                "study": study,
                                "configuration": label,
                                "seed": seed,
                                "message": message,
                                "batch": batch + 1,
                                "exposures": exposures,
                                "old_engagement": ea,
                                "new_engagement": eb,
                                "old_rate": ea / exposures,
                                "new_rate": eb / exposures,
                            }
                            for action in ["like", "comment", "share", "ignore"]:
                                row[f"old_{action}"] = ca[action]
                                row[f"new_{action}"] = cb[action]
                            writer.writerow(row)
                            curve_groups[study, label, message, batch + 1].append((ea, eb, exposures))
                print({"reopened_verified": study, "configuration": label}, flush=True)
    csv_write(dest / "old-new-path-metrics.csv", path_rows)
    csv_write(dest / "old-new-exposure-order.csv", exposure_rows)
    ordinary = t_quantile(0.975)
    param_critical = t_quantile(1 - 0.05 / (2 * 123))
    index_critical = t_quantile(1 - 0.05 / (2 * 120))
    summary = []
    comparisons = []
    old_new = []
    contrasts = []
    for study in ["parameters", "index"]:
        labels = [r[0] for r in CONFIGURATIONS] if study == "parameters" else list(live_study.ARMS)
        baseline = "w0-h3" if study == "parameters" else "baseline"
        for label in labels:
            for message in ["message_1", "message_2", "message_3", "all"]:
                for metric in METRICS:
                    values = [data[study, label, s, message][metric] for s in SEEDS]
                    prior = [old_data[study, label, s, message][metric] for s in SEEDS]
                    summary.append(
                        {
                            "study": study,
                            "configuration": label,
                            "message": message,
                            "metric": metric,
                            "n": 100,
                            "old_mean": statistics.mean(prior),
                            **_estimate(values, ordinary),
                        }
                    )
                    changes = [x - y for x, y in zip(values, prior, strict=True)]
                    old_new.append(
                        {
                            "study": study,
                            "configuration": label,
                            "message": message,
                            "metric": metric,
                            "n_pairs": 100,
                            **_estimate(changes, ordinary),
                        }
                    )
                    if study == "index" and label != baseline:
                        diffs = [
                            data[study, label, s, message][metric] - data[study, baseline, s, message][metric]
                            for s in SEEDS
                        ]
                        simultaneous = _estimate(diffs, index_critical)
                        comparisons.append(
                            {
                                "arm": label,
                                "message": message,
                                "metric": metric,
                                "n_pairs": 100,
                                **_estimate(diffs, ordinary),
                                "family_lower": simultaneous["lower"],
                                "family_upper": simultaneous["upper"],
                                "zero_difference_paths": sum(x == 0 for x in diffs),
                            }
                        )
            if study == "parameters":
                for a, b in [("message_1", "message_2"), ("message_1", "message_3"), ("message_2", "message_3")]:
                    differences = [
                        data[study, label, s, a]["engagement_rate"] - data[study, label, s, b]["engagement_rate"]
                        for s in SEEDS
                    ]
                    delta = [
                        v
                        - (
                            data[study, baseline, s, a]["engagement_rate"]
                            - data[study, baseline, s, b]["engagement_rate"]
                        )
                        for v, s in zip(differences, SEEDS, strict=True)
                    ]
                    effect = _estimate(delta, param_critical)
                    difference = _estimate(differences, param_critical)
                    contrasts.append(
                        {
                            "configuration": label,
                            "contrast": a + "-" + b,
                            **{f"difference_{k}": v for k, v in difference.items()},
                            **{f"delta_{k}": v for k, v in effect.items()},
                            "delta_ordinary_lower": statistics.mean(delta) - ordinary * effect["mcse"],
                            "delta_ordinary_upper": statistics.mean(delta) + ordinary * effect["mcse"],
                            "epsilon": 0.02,
                            "mc_halfwidth_target": 0.005,
                            "mc_precision_met": ordinary * effect["mcse"] <= 0.005,
                            "amplitude": "baseline"
                            if label == baseline
                            else "equivalent_in_tested_range"
                            if effect["lower"] >= -0.02 and effect["upper"] <= 0.02
                            else "sensitive"
                            if effect["lower"] > 0.02 or effect["upper"] < -0.02
                            else "undetermined",
                        }
                    )
    csv_write(dest / "arm-parameter-estimates.csv", summary)
    csv_write(dest / "old-new-paired-estimates.csv", old_new)
    csv_write(dest / "index-paired-estimates.csv", comparisons)
    csv_write(dest / "parameter-message-contrasts.csv", contrasts)
    curves = []
    for (study, label, message, batch), values in sorted(curve_groups.items()):
        curves.append(
            {
                "study": study,
                "configuration": label,
                "message": message,
                "batch": batch,
                "exposures": values[0][2],
                "old_engagement_mean": statistics.mean(v[0] for v in values),
                "new_engagement_mean": statistics.mean(v[1] for v in values),
                "old_rate_mean": statistics.mean(v[0] / v[2] for v in values),
                "new_rate_mean": statistics.mean(v[1] / v[2] for v in values),
            }
        )
    csv_write(dest / "old-new-mean-curves.csv", curves)
    samples = bank.read_json(ROOT / "preflight-final/samples.json")
    sample_lines = ["| 臂 | 与新基准重叠/1000 | 与旧同臂重叠/1000 |", "|---|---:|---:|"]
    sample_lines += [f"| {r['arm']} | {r['overlap_new_baseline']} | {r['overlap_old_same_arm']} |" for r in samples]
    table = ["| 研究/臂 | 旧互动率均值 | 新互动率均值 | 新−旧pp |", "|---|---:|---:|---:|"]
    for r in summary:
        if r["message"] == "all" and r["metric"] == "engagement_rate":
            table.append(
                f"| {r['study']}/{r['configuration']} | {100 * r['old_mean']:.3f}% | {100 * r['mean']:.3f}% | {100 * (r['mean'] - r['old_mean']):+.3f} |"
            )
    report = f"""# 十话题 GPT/P0 推荐参数与指标研究

两项研究在独立run内完成：21参数×100seed=2100路径，原7臂×100seed=700路径；每路径1800曝光、30完整三消息barrier。全量重开独立复验合计5040000曝光、84000 barriers。仅GPT-5.6 Sol/P0、既有Pi OAuth订阅通道；未调用其他模型，未修改论文或canonical。

新网络源identity/manifest hash：{prep["network_source_manifest_sha256"]}；P95=5；正式十采集话题及holdout/建边规则沿前阶段合同。基准sample按新网络原规则重新构建；固定旧样本仅前阶段审计。fixed/rebuilt臂按原协议区分，不增删7臂。

{chr(10).join(sample_lines)}

Local weights固定/重建100个seed路径完全一致（实际逐字段验证）；参数w0-h3与指标baseline100路径完全一致。这些不是额外独立重复证据。新旧基准仅646重合；Local p99 rebuilt与新基准仅23重合，差异含样本构成影响。

## 行为结果与新旧对照

{chr(10).join(table)}

完整每消息四行为计数、逐seed路径、曝光集合/排序差异和累计曲线见同目录CSV。不能把终点相同解读为排序/过程相同。新旧差异混合网络口径、样本构成、指标变体及模型服务时点；不声称纯指标因果效应或普遍稳健。

## 不确定性

以100行为seed为统计单位；seed不重复模型判断。原参数Bonferroni家族123、指标家族120保持；Student-t df99配对/普通区间与同时区间均保留。参数ε=2pp，普通区间半宽目标0.5pp；详细message contrasts给出是否达到。区间仅为固定判断与数据条件下的行为Monte Carlo误差，不含模型服务漂移、样本或真实平台不确定性。

## 调用、来源和费用

合并17520判断，复用10308、新成功{closure["new_successes"]}。物理请求{closure["physical_requests"]}，资格{closure["qualification_requests"]}，重试{closure["retry_requests"]}，峰值并发{closure["maximum_observed_in_flight"]}。请求/响应账本为formal-bank/collection/attempts.jsonl，先fsync intent再dispatch，settlement与bank来源均逐条复验。observed model全部成功响应为gpt-5.6-sol；P0、low、256 total completion及原条件保持。

用户2026-10-06明确授权直接执行且无总额度上限；总调用/费用ceiling=null，不沿用此前未确认的US$100提案。未切付费API。可核验名义参考消耗小计{closure["known_nominal_cost_usd"]:.6f} USD；费用未知请求{closure["nominal_cost_unknown_attempts"]}仍未按零处理。actual incremental cash fee=null（通道未提供现金账单），不把名义价格当发票。费用/调用核验见collection-verified.json及cost-ledger.json。

保留原draw anchor {prep["draw_anchor"]}；新bank、臂名、输出目录和访问顺序不改随机数。输入相同的判断复用旧记录；新输入判断独立记录真实请求、模型与服务时间。先前activity_p99 unknown输入不在本轮重选七臂universe内，未沿用旧“不曝光”证明、未重发未知请求、未填充假判断。

## 验收和限制

全部2800路径逐批重开独立复算排序、并列user_id顺序、种子优先、逐pair最多一次、概率实现、互斥行为和全批反馈；逐路径hash、完整矩阵与源bank绑定核对。旧源文件hash前后一致，保留前阶段全样本成果。测试命令、差分/回滚和未执行检查需同时参阅最终VERIFICATION.txt。

未进行新增四模型研究、100次LLM重复、现金发票核对、论文更新、canonical发布/公网下载验收。后续需同步网络/样本方法、参数与指标新统计、曲线与CSV/JSON下载和研究身份；四模型留到最后，发布须另建immutable release。
"""
    (dest / "REPORT.md").write_text(report)
    _publish(ROOT / "cost-ledger.json", closure, rows=False)
    evidence = {
        "schema_version": "ten-topic-gpt-studies-reopened-evidence-v1",
        "status": "complete_verified",
        "paths": 2800,
        "exposures": 5040000,
        "batch_barriers": 84000,
        "provider_calls_during_replay": 0,
        "bank_sha256": closure["bank_sha256"],
        "path_manifest_sha256": bank.file_hash(ROOT / "formal-paths/manifest.json"),
        "ordinary_t_df99": ordinary,
        "parameter_family": 123,
        "index_family": 120,
        "source_hashes_equal": True,
        "report_artifacts": {f.name: bank.file_hash(f) for f in dest.iterdir() if f.is_file()},
    }
    for path, digest in bank.read_json(ROOT / "preflight-final/protected-source-hashes.json").items():
        bank.bound(Path(path), digest, "protected source")
    _publish(dest / "evidence.json", evidence, rows=False)
    print(json.dumps(evidence, sort_keys=True), flush=True)


if __name__ == "__main__":
    run()
