"""Approved new-network studies: require a independently closed real bank, no Provider here."""

import fcntl
import json
from pathlib import Path

import fast_paths
import live_study
import verify_collection

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_collection import _publish
from llm_abm_sim._parameter_study import CONFIGURATIONS, SEEDS
from llm_abm_sim.concurrent_message_experiment import _prepare_concurrent_runtime_inputs

ROOT = Path(__file__).resolve().parent


def run():
    if (ROOT / "explicit-unknown-reissue" / "attempts.jsonl").exists():
        import bank_union

        closed = bank_union.validate(ROOT)
        bank_root = ROOT / "final-bank"
    else:
        closed = verify_collection.validate(ROOT / "formal-bank")
        bank_root = ROOT / "formal-bank"
    _publish(ROOT / "collection-verified.json", closed, rows=False)
    prep = bank.read_json(bank_root / "preparation.json")
    records = live_study.frozen.read_rows(bank_root / "closed-bank.jsonl")
    cfg, legacy, source = bank._inputs(bank.read_json(Path(prep["audit"]["path"])))
    cfg = cfg.model_copy(update={"network_scope": "final_collected_topics"})
    base = _prepare_concurrent_runtime_inputs(cfg)
    samples = {r["arm"]: r for r in bank.read_json(ROOT / "preflight-final/samples.json")}
    destination = ROOT / "formal-paths"
    destination.mkdir(exist_ok=True)
    manifest = {
        "schema_version": "ten-topic-gpt-parameter-index-paths-v1",
        "provider_calls": 0,
        "production_deploy_eligible": False,
        "bank_sha256": closed["bank_sha256"],
        "preparation_sha256": bank.file_hash(bank_root / "preparation.json"),
        "draw_anchor": prep["draw_anchor"],
        "network_scope": "final_collected_topics",
        "network_source_manifest_sha256": prep["network_source_manifest_sha256"],
        "configurations": CONFIGURATIONS,
        "seeds": SEEDS,
        "arms": live_study.ARMS,
        "paths": {},
    }
    campaigns = {}
    with (destination / "writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for study in ["parameters", "index"]:
            pathdir = destination / study
            pathdir.mkdir(exist_ok=True)
            runs = CONFIGURATIONS if study == "parameters" else [(arm, (0.5, 0.3, 0.2), 3) for arm in live_study.ARMS]
            for label, weights, threshold in runs:
                arm = "baseline" if study == "parameters" else label
                if arm not in campaigns:
                    prepared, _ = live_study.arm_inputs(cfg, base, arm)
                    if (
                        prepared.cohort.sample_user_ids != samples[arm]["sample_user_ids"]
                        or prepared.cohort.seed_user_ids != samples[arm]["seed_user_ids"]
                    ):
                        raise ValueError("arm membership differs from authorized exact-input preparation")
                    campaigns[arm] = fast_paths.Campaign(cfg, prepared, prep["request_condition"], records)
                campaign = campaigns[arm]
                for seed in SEEDS:
                    name = f"{label}-s{seed}.json"
                    target = pathdir / name
                    identity = {
                        "study": study,
                        "configuration": label,
                        "seed": seed,
                        "weights": weights,
                        "neighbor_saturation": threshold,
                        "arm": arm,
                        "bank_sha256": closed["bank_sha256"],
                        "draw_anchor": prep["draw_anchor"],
                        "preparation_sha256": manifest["preparation_sha256"],
                        "network_source_manifest_sha256": prep["network_source_manifest_sha256"],
                    }
                    if target.exists():
                        document = bank.read_json(target)
                        if document["identity"] != json.loads(json.dumps(identity)) or document[
                            "path_sha256"
                        ] != bank.fingerprint(document["path"]):
                            raise ValueError("persisted path identity/hash differs")
                    else:
                        result = campaign.execute(prep["draw_anchor"], seed, tuple(weights), threshold)
                        if len(result["terminals"]) != 1800 or len(result["barriers"]) != 30:
                            raise ValueError("formal path topology incomplete")
                        document = {"identity": identity, "path": result, "path_sha256": bank.fingerprint(result)}
                        _publish(target, document, rows=False)
                    campaign.verify(document["path"], prep["draw_anchor"], seed, tuple(weights), threshold)
                    manifest["paths"][f"{study}/{name}"] = bank.file_hash(target)
                print(
                    {
                        "study": study,
                        "configuration": label,
                        "completed_verified_paths": 100,
                        "total_verified": len(manifest["paths"]),
                    },
                    flush=True,
                )
        if len(manifest["paths"]) != 2800:
            raise ValueError("full study matrix incomplete")
        for seed in SEEDS:
            fixed = bank.read_json(destination / f"index/local_weights_fixed-s{seed}.json")["path"]
            rebuilt = bank.read_json(destination / f"index/local_weights_rebuilt-s{seed}.json")["path"]
            baseline = bank.read_json(destination / f"index/baseline-s{seed}.json")["path"]
            parameter = bank.read_json(destination / f"parameters/w0-h3-s{seed}.json")["path"]
            if fixed != rebuilt:
                raise ValueError("Local weight fixed/rebuilt paths differ despite identical inputs")
            if baseline != parameter:
                raise ValueError("shared baseline differs across two studies")
        for path, digest in bank.read_json(ROOT / "preflight-final/protected-source-hashes.json").items():
            bank.bound(Path(path), digest, "protected source")
        bank.v2._assert_source_unchanged(source)
        manifest["status"] = "complete_verified"
        manifest["local_fixed_rebuilt_100_paths_equal"] = True
        manifest["shared_baseline_100_paths_equal"] = True
        _publish(destination / "manifest.json", manifest, rows=False)
        print("All 2800 real-bank paths executed and independently verified; Provider calls during paths=0", flush=True)


if __name__ == "__main__":
    run()
