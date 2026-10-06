from pathlib import Path
from llm_abm_sim import _parameter_judgment_bank as bank
import bank_union, live_study

root = Path(__file__).resolve().parent
parent = root / "unattempted-stage-02"
dest = root / "unattempted-stage-03"
if dest.exists():
    raise ValueError("new stage required")
prep, accepted, unknown, intents, settled, peak = bank_union.stage_facts(parent, True)
assert len(accepted) == 138 and len(unknown) == 1 and len(intents) == len(settled) == 140
attempted = {v["pair_key"] for v in intents if v["purpose"] == "judgment"}
missing = [r for r in live_study.frozen.read_rows(parent / "missing-pairs.jsonl") if live_study.key(r) not in attempted]
assert len(missing) == 1025 and not attempted & {live_study.key(r) for r in missing}
old = live_study.frozen.read_rows(parent / "accepted-bank.jsonl") + list(accepted.values())
assert len(old) == 16492
unknowns = prep["deferred_unknowns"] + unknown
new = {
    **prep,
    "accepted": len(old),
    "missing": len(missing),
    "universe": len(old) + len(missing),
    "overall_status": "partial_three_unknowns_retained",
    "deferred_unknowns": unknowns,
    "stage_lineage": {
        "parent_root": str(parent),
        "parent_preparation_sha256": bank.file_hash(parent / "preparation.json"),
        "parent_ledger_sha256": bank.file_hash(parent / "collection/attempts.jsonl"),
        "unknowns": unknown,
        "unknowns_automatically_reissued": False,
    },
}
new["live_authorization_caps"] = {**prep["live_authorization_caps"], "successes": len(missing)}
new["implementation_hashes"] = {
    name: bank.file_hash(root / name)
    for name in ["merged_collection_diagnostic.py", "unknown_diagnostics.py", "live_study.py", "offline_path_engine.py"]
}
dest.mkdir()
(dest / "collection").mkdir()
bank.write_json(dest / "preparation.json", new)
bank.write_jsonl(dest / "accepted-bank.jsonl", old)
bank.write_jsonl(dest / "missing-pairs.jsonl", missing)
auth = bank.read_json(parent / "execution-authorization.json")
auth["preparation_sha256"] = bank.file_hash(dest / "preparation.json")
auth["authorized_scope"] = "never-attempted only; all three unknowns excluded"
bank.write_json(dest / "execution-authorization.json", auth)
bank.write_json(
    dest / "collection/concurrency-authorization.json",
    {
        "schema_version": "ten-topic-gpt-merged-concurrency-v1",
        "preparation_sha256": auth["preparation_sha256"],
        "maximum_concurrency": 5,
        "reason": "explicit_user_request_20261006_no_total_ceiling",
    },
)
bank.write_json(
    dest / "artifact-manifest.json",
    {
        "schema_version": new["schema_version"],
        "sha256": {p.name: bank.file_hash(p) for p in dest.iterdir() if p.is_file()},
    },
)
bank.write_json(
    root / "UNKNOWN_RECONCILIATION_03.json",
    {
        "overall_status": "partial",
        "new_successes_preserved": 6184,
        "unknowns": unknowns,
        "unattempted_inputs": 1025,
        "automatic_unknown_reissues": 0,
    },
)
print("diagnostic stage: known=16492; never-attempted=1025; three unknowns retained; model/request settings unchanged")
