"""Preserve the stopped stage and collect only inputs never dispatched there."""

from pathlib import Path

import live_study
import merged_collection

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_collection import _events
from llm_abm_sim.decision import EngageDecision
from llm_abm_sim.provider_accounting import ProviderAccounting

root = Path(__file__).resolve().parent
parent = root / "formal-bank"
dest = root / "unattempted-stage-01"
if dest.exists():
    raise ValueError("new unattempted stage required")
prep = merged_collection._load(parent)
events = _events(parent / "collection/attempts.jsonl", bank.file_hash(parent / "preparation.json"))
expected = {live_study.key(r): r for r in live_study.frozen.read_rows(parent / "missing-pairs.jsonl")}
pending = {}
accepted = {}
unknown = []
attempted = set()
qualified = False
for ordinal, event in enumerate(events):
    assert event["sequence"] == ordinal
    v = event["payload"]
    if event["kind"] == "intent":
        assert v["intent_sequence"] == ordinal
        pending[ordinal] = v
        if v["purpose"] == "judgment":
            attempted.add(v["pair_key"])
    else:
        intent = pending.pop(v["intent_sequence"])
        if v["outcome"] == "succeeded":
            a = ProviderAccounting.model_validate(v["accounting"])
            assert a.observed_model_counts == {"gpt-5.6-sol": 1} and a.output_tokens <= 256
            if intent["purpose"] == "qualification":
                qualified = True
            else:
                r = v["bank_entry"]
                key = live_study.key(r)
                assert key == intent["pair_key"] and key not in accepted
                assert all(r[k] == value for k, value in expected[key].items())
                EngageDecision.model_validate(r["decision"])
                accepted[key] = {
                    **r,
                    "collection_event_sha256": event["sha256"],
                    "collected_at_utc": event["recorded_at_utc"],
                }
        elif v["outcome"] == "unknown":
            unknown.append(
                {
                    "key": intent["pair_key"],
                    "intent_sequence": v["intent_sequence"],
                    "event_sha256": event["sha256"],
                    "input": expected[intent["pair_key"]],
                }
            )
        else:
            raise ValueError("unexpected non-success outside explicit unknown")
assert not pending and qualified and len(unknown) == 1 and len(accepted) == 2067
missing = [r for k, r in expected.items() if k not in attempted]
assert len(missing) == 5144 and not {live_study.key(r) for r in missing} & attempted
old = live_study.frozen.read_rows(parent / "accepted-bank.jsonl") + list(accepted.values())
assert len(old) == 12375
new = {
    **prep,
    "accepted": len(old),
    "missing": len(missing),
    "universe": len(old) + len(missing),
    "overall_universe": 17520,
    "overall_status": "partial_one_unknown_retained",
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
auth["authorized_scope"] = "never_attempted_inputs_only; original unknown excluded"
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
    root / "UNKNOWN_RECONCILIATION.json",
    {
        "overall_status": "partial",
        "new_successes_preserved": 2067,
        "unknowns": unknown,
        "unattempted_inputs": 5144,
        "original_unknown_not_reissued": True,
        "requires_explicit_unknown_reissue_confirmation": True,
    },
)
print("new stage: preserved judgments=12375; never-attempted missing=5144; original unknown retained and excluded")
