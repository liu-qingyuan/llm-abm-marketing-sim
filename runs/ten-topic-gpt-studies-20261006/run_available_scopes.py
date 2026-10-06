"""Execute only fully judged scopes, keeping the 2800-path overall objective incomplete."""

import fcntl
import json
from pathlib import Path

import bank_union
import fast_paths
import live_study
import merged_collection

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_collection import _publish
from llm_abm_sim._parameter_study import CONFIGURATIONS, SEEDS
from llm_abm_sim.concurrent_message_experiment import _prepare_concurrent_runtime_inputs

ROOT = Path(__file__).resolve().parent
STAGES = ["formal-bank", "unattempted-stage-01", "unattempted-stage-02", "unattempted-stage-03"]


def run():
    records = live_study.frozen.read_rows(ROOT / "formal-bank/accepted-bank.jsonl")
    unknowns = []
    dispatched = set()
    facts = []
    for index, name in enumerate(STAGES):
        stage = ROOT / name
        f = bank_union.stage_facts(stage, index < 3)
        prep, accepted, unknown, intents, settled, peak = f
        if live_study.frozen.read_rows(stage / "accepted-bank.jsonl") != records:
            raise ValueError("recovery source prefix differs")
        keys = {v["pair_key"] for v in intents if v["purpose"] == "judgment"}
        if keys & dispatched:
            raise ValueError("automatic redispatch of prior input")
        dispatched.update(keys)
        records += list(accepted.values())
        unknowns += unknown
        facts.append(f)
    if len(records) != 17517 or len(unknowns) != 3:
        raise ValueError("actual partial-bank scope differs")
    published = live_study.frozen.read_rows(ROOT / "unattempted-stage-03/closed-bank.jsonl")
    if sorted(records, key=lambda r: (r["user_id"], r["message_id"])) != published:
        raise ValueError("published recovered prefix differs")
    original = merged_collection._load(ROOT / "formal-bank")
    cfg, _, source = bank._inputs(bank.read_json(Path(original["audit"]["path"])))
    cfg = cfg.model_copy(update={"network_scope": "final_collected_topics"})
    base = _prepare_concurrent_runtime_inputs(cfg)
    dest = ROOT / "ready-formal-paths"
    dest.mkdir(exist_ok=True)
    summary = {
        "schema_version": "ten-topic-fully-judged-scope-paths-v1",
        "overall_status": "partial_three_unknowns_retained",
        "overall_required_paths": 2800,
        "completed_verified_paths": {},
        "unexecuted_arm": "local_p99_rebuilt",
        "retained_unknowns": unknowns,
        "draw_anchor": original["draw_anchor"],
        "provider_calls_during_paths": 0,
        "source_ledgers": [
            {
                "path": str(ROOT / n / "collection/attempts.jsonl"),
                "sha256": bank.file_hash(ROOT / n / "collection/attempts.jsonl"),
            }
            for n in STAGES
        ],
    }
    cache = {}
    scope_banks = {}
    with (dest / "writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for study in ["parameters", "index"]:
            runs = (
                CONFIGURATIONS
                if study == "parameters"
                else [(a, (0.5, 0.3, 0.2), 3) for a in live_study.ARMS if a != "local_p99_rebuilt"]
            )
            pathdir = dest / study
            pathdir.mkdir(exist_ok=True)
            for label, weights, h in runs:
                arm = "baseline" if study == "parameters" else label
                if arm not in cache:
                    prepared, _ = live_study.arm_inputs(cfg, base, arm)
                    campaign = fast_paths.Campaign(cfg, prepared, original["request_condition"], records)
                    scoped = sorted(
                        campaign.entries.values(),
                        key=lambda r: (r["user_id"], r["message_id"], r["client_condition_sha256"]),
                    )
                    if len(scoped) != 3000:
                        raise ValueError("required scope lacks complete candidate bank")
                    scope_id = bank.fingerprint(scoped)
                    scope_banks[arm] = {
                        "scope_bank_sha256": scope_id,
                        "required_inputs": 3000,
                        "sample_user_ids": prepared.cohort.sample_user_ids,
                        "seed_user_ids": prepared.cohort.seed_user_ids,
                    }
                    cache[arm] = campaign
                for seed in SEEDS:
                    identity = {
                        "study": study,
                        "configuration": label,
                        "seed": seed,
                        "weights": weights,
                        "neighbor_saturation": h,
                        "arm": arm,
                        "scope_bank_sha256": scope_banks[arm]["scope_bank_sha256"],
                        "draw_anchor": original["draw_anchor"],
                        "network_source_manifest_sha256": original["network_source_manifest_sha256"],
                    }
                    path = pathdir / f"{label}-s{seed}.json"
                    if path.exists():
                        document = bank.read_json(path)
                        if document["identity"] != json.loads(json.dumps(identity)) or document[
                            "path_sha256"
                        ] != bank.fingerprint(document["path"]):
                            raise ValueError("scope path identity differs")
                    else:
                        payload = cache[arm].execute(original["draw_anchor"], seed, tuple(weights), h)
                        document = {"identity": identity, "path": payload, "path_sha256": bank.fingerprint(payload)}
                        _publish(path, document, rows=False)
                    cache[arm].verify(document["path"], original["draw_anchor"], seed, tuple(weights), h)
                    summary["completed_verified_paths"][f"{study}/{path.name}"] = bank.file_hash(path)
                print(
                    {
                        "study": study,
                        "configuration": label,
                        "scope_complete_paths": 100,
                        "total_verified": len(summary["completed_verified_paths"]),
                    },
                    flush=True,
                )
                _publish(dest / "partial-manifest.json", summary, rows=False)
        if len(summary["completed_verified_paths"]) != 2700:
            raise ValueError("fully covered scope count differs")
        for seed in SEEDS:
            a = bank.read_json(dest / f"index/local_weights_fixed-s{seed}.json")["path"]
            b = bank.read_json(dest / f"index/local_weights_rebuilt-s{seed}.json")["path"]
            baseline = bank.read_json(dest / f"index/baseline-s{seed}.json")["path"]
            parameter = bank.read_json(dest / f"parameters/w0-h3-s{seed}.json")["path"]
            if a != b or baseline != parameter:
                raise ValueError("shared-input scope paths differ")
        for path, digest in bank.read_json(ROOT / "preflight-final/protected-source-hashes.json").items():
            bank.bound(Path(path), digest, "protected source")
        bank.v2._assert_source_unchanged(source)
        summary["scope_banks"] = scope_banks
        summary["parameter_study_status"] = "complete_verified"
        summary["index_study_status"] = "partial_600_of_700_paths"
        _publish(dest / "partial-manifest.json", summary, rows=False)
        print("2700 fully judged paths verified; full 2800-path objective remains incomplete", flush=True)


if __name__ == "__main__":
    run()
