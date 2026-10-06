"""Third segment: preserve both stopped stages and dispatch only never-attempted keys."""

from pathlib import Path
from llm_abm_sim import _parameter_judgment_bank as bank
import bank_union, merged_collection, live_study

root = Path(__file__).resolve().parent
parent = root / "unattempted-stage-01"
dest = root / "unattempted-stage-02"
if dest.exists():
    raise ValueError("new output required")
prep, accepted, unknown, intents, settlements, peak = bank_union.stage_facts(parent, True)
assert len(accepted) == 3979 and len(unknown) == 1 and len(intents) == len(settlements) == 3981
attempted = {r["pair_key"] for r in intents if r["purpose"] == "judgment"}
missing = [r for r in live_study.frozen.read_rows(parent / "missing-pairs.jsonl") if live_study.key(r) not in attempted]
assert len(missing) == 1164 and not attempted & {live_study.key(r) for r in missing}
old = live_study.frozen.read_rows(parent / "accepted-bank.jsonl") + list(accepted.values())
assert len(old) == 16354
firstprep, firstaccepted, firstunknown, _, _, _ = bank_union.stage_facts(root / "formal-bank", True)
deferred = firstunknown + unknown
new = {
    **prep,
    "accepted": len(old),
    "missing": len(missing),
    "universe": len(old) + len(missing),
    "overall_universe": 17520,
    "overall_status": "partial_two_unknowns_retained",
    "deferred_unknowns": deferred,
    "stage_lineage": {
        "parent_root": str(parent),
        "parent_preparation_sha256": bank.file_hash(parent / "preparation.json"),
        "parent_ledger_sha256": bank.file_hash(parent / "collection/attempts.jsonl"),
        "unknowns": unknown,
        "unknowns_automatically_reissued": False,
    },
    "status": "authorized_unattempted_inputs_only",
}
new["live_authorization_caps"] = {**prep["live_authorization_caps"], "successes": len(missing)}
dest.mkdir()
(dest / "collection").mkdir()
bank.write_json(dest / "preparation.json", new)
bank.write_jsonl(dest / "accepted-bank.jsonl", old)
bank.write_jsonl(dest / "missing-pairs.jsonl", missing)
auth = bank.read_json(parent / "execution-authorization.json")
auth["preparation_sha256"] = bank.file_hash(dest / "preparation.json")
auth["authorized_scope"] = "only never-attempted inputs; both unknowns excluded"
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
    root / "UNKNOWN_RECONCILIATION_02.json",
    {
        "overall_status": "partial",
        "new_successes_preserved": 6046,
        "unknowns": deferred,
        "unattempted_inputs": 1164,
        "automatic_unknown_reissues": 0,
    },
)
print("Third segment: accepted=16354; never-attempted=1164; two unknowns retained/excluded")
