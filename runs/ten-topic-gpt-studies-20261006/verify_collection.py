"""Independent provenance, coverage and accounting acceptance for the new bank."""

from collections import Counter
from pathlib import Path

import live_study as study
import merged_collection

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_collection import _events
from llm_abm_sim.decision import EngageDecision
from llm_abm_sim.provider_accounting import ProviderAccounting


def validate(root: Path):
    prep = merged_collection._load(root)
    identity = bank.file_hash(root / "preparation.json")
    events = _events(root / "collection/attempts.jsonl", identity)
    old = study.frozen.read_rows(root / "accepted-bank.jsonl")
    expected = {study.key(r): r for r in study.frozen.read_rows(root / "missing-pairs.jsonl")}
    accepted = {}
    pending = {}
    peak = 0
    qualified = False
    nominal = []
    settled = []
    intents = []
    auth = bank.file_hash(root / "collection/concurrency-authorization.json")
    for ordinal, event in enumerate(events):
        if event["sequence"] != ordinal:
            raise ValueError("ledger ordinal crossed")
        v = event["payload"]
        if event["kind"] == "intent":
            if v["intent_sequence"] != ordinal or v["concurrency_authorization_sha256"] != auth:
                raise ValueError("intent binding differs")
            if v["purpose"] == "judgment":
                if not qualified or v["pair_key"] not in expected or v["pair_key"] in accepted:
                    raise ValueError("unqualified or crossed input")
                if v["client_condition_sha256"] != expected[v["pair_key"]]["client_condition_sha256"]:
                    raise ValueError("intent input differs")
            elif v["purpose"] != "qualification":
                raise ValueError("unknown request purpose")
            if any(p["pair_key"] == v["pair_key"] for p in pending.values()):
                raise ValueError("duplicate in-flight input")
            pending[ordinal] = v
            intents.append(v)
            peak = max(peak, len(pending))
            if peak > 5:
                raise ValueError("in-flight ceiling exceeded")
        elif event["kind"] == "settled":
            intent = pending.pop(v["intent_sequence"])
            settled.append(v)
            nominal.append(v["subscription_nominal_cost_usd"])
            if v["outcome"] == "succeeded":
                a = ProviderAccounting.model_validate(v["accounting"])
                if (
                    a.observed_model_counts != {"gpt-5.6-sol": 1}
                    or a.provider_response_count != 1
                    or a.successful_decision_count != 1
                    or a.usage_complete_response_count != 1
                    or a.output_tokens is None
                    or a.output_tokens > 256
                ):
                    raise ValueError("response accounting differs")
                if intent["purpose"] == "qualification":
                    qualified = True
                else:
                    row = v["bank_entry"]
                    k = study.key(row)
                    if (
                        k != intent["pair_key"]
                        or k in accepted
                        or any(row[n] != value for n, value in expected[k].items())
                    ):
                        raise ValueError("settlement input differs")
                    EngageDecision.model_validate(row["decision"])
                    accepted[k] = {
                        **row,
                        "collection_event_sha256": event["sha256"],
                        "collected_at_utc": event["recorded_at_utc"],
                    }
            elif v["outcome"] != "retryable_failure":
                raise ValueError("unknown or terminal failure; bank not accepted")
        else:
            raise ValueError("unknown ledger event")
    if pending or not qualified or set(accepted) != set(expected):
        raise ValueError("real bank coverage incomplete")
    tries = Counter(i["pair_key"] for i in intents if i["purpose"] == "judgment")
    qual = sum(i["purpose"] == "qualification" for i in intents)
    retries = sum(n - 1 for n in tries.values())
    if max(tries.values()) > 3 or qual > 2:
        raise ValueError("per-input protocol ceiling exceeded")
    actual = study.frozen.read_rows(root / "closed-bank.jsonl")
    merged = sorted([*old, *accepted.values()], key=lambda r: (r["user_id"], r["message_id"]))
    if actual != merged or len({study.key(r) for r in actual}) != prep["universe"]:
        raise ValueError("published bank differs")
    closure = bank.read_json(root / "collection/closure.json")
    fact = {
        "schema_version": "ten-topic-gpt-merged-collection-closure-v1",
        "status": "complete",
        "bank_sha256": bank.file_hash(root / "closed-bank.jsonl"),
        "unique_pairs": len(actual),
        "new_successes": len(accepted),
        "physical_requests": len(intents),
        "qualification_requests": qual,
        "retry_requests": retries,
        "attempt_ledger_sha256": bank.file_hash(root / "collection/attempts.jsonl"),
        "known_nominal_cost_usd": sum(x for x in nominal if x is not None),
        "nominal_cost_unknown_attempts": sum(x is None for x in nominal),
        "actual_incremental_fee": None,
        "production_deploy_eligible": False,
        "concurrency_authorization_sha256": auth,
    }
    if closure != fact:
        raise ValueError("collection closure counters differ")
    for path, digest in bank.read_json(root.parent / "preflight-final/protected-source-hashes.json").items():
        bank.bound(Path(path), digest, "protected historical source")
    return {
        **fact,
        "verified": True,
        "maximum_observed_in_flight": peak,
        "input_tokens_known_subtotal": sum(v["accounting"]["input_tokens"] or 0 for v in settled),
        "output_tokens_known_subtotal": sum(v["accounting"]["output_tokens"] or 0 for v in settled),
        "first_request_utc": events[0]["recorded_at_utc"],
        "last_response_utc": events[-1]["recorded_at_utc"],
        "total_physical_request_ceiling": None,
        "total_cost_ceiling": None,
    }
