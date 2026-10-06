"""Read-only recovery lineage acceptance; retain unknown requests, never call Provider."""

from collections import Counter
from pathlib import Path

import live_study
import merged_collection

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_collection import _events, _publish
from llm_abm_sim.decision import EngageDecision
from llm_abm_sim.provider_accounting import ProviderAccounting

ROOT = Path(__file__).resolve().parent


def stage_facts(root, allow_unknown):
    prep = merged_collection._load(root)
    events = _events(root / "collection/attempts.jsonl", bank.file_hash(root / "preparation.json"))
    expected = {live_study.key(r): r for r in live_study.frozen.read_rows(root / "missing-pairs.jsonl")}
    pending = {}
    accepted = {}
    intents = []
    settled = []
    unknown = []
    qualified = False
    peak = 0
    authorization = bank.file_hash(root / "collection/concurrency-authorization.json")
    for ordinal, event in enumerate(events):
        assert event["sequence"] == ordinal
        v = event["payload"]
        if event["kind"] == "intent":
            assert v["intent_sequence"] == ordinal and v["concurrency_authorization_sha256"] == authorization
            assert not any(x["pair_key"] == v["pair_key"] for x in pending.values())
            if v["purpose"] == "judgment":
                assert qualified and v["pair_key"] in expected and v["pair_key"] not in accepted
                assert v["client_condition_sha256"] == expected[v["pair_key"]]["client_condition_sha256"]
            else:
                assert v["purpose"] == "qualification"
            pending[ordinal] = v
            intents.append(v)
            peak = max(peak, len(pending))
            assert peak <= 5
        else:
            assert event["kind"] == "settled"
            intent = pending.pop(v["intent_sequence"])
            settled.append(v)
            if v["outcome"] == "succeeded":
                a = ProviderAccounting.model_validate(v["accounting"])
                assert (
                    a.observed_model_counts == {"gpt-5.6-sol": 1}
                    and a.provider_response_count == a.successful_decision_count == a.usage_complete_response_count == 1
                    and a.output_tokens <= 256
                )
                if intent["purpose"] == "qualification":
                    qualified = True
                else:
                    r = v["bank_entry"]
                    k = live_study.key(r)
                    assert k == intent["pair_key"] and k not in accepted
                    assert all(r[n] == value for n, value in expected[k].items())
                    EngageDecision.model_validate(r["decision"])
                    accepted[k] = {
                        **r,
                        "collection_event_sha256": event["sha256"],
                        "collected_at_utc": event["recorded_at_utc"],
                    }
            elif v["outcome"] == "unknown":
                assert allow_unknown
                unknown.append({"key": intent["pair_key"], "event_sha256": event["sha256"]})
            else:
                assert v["outcome"] == "retryable_failure"
    assert qualified and not pending
    tries = Counter(v["pair_key"] for v in intents if v["purpose"] == "judgment")
    assert max(tries.values()) <= 3 and sum(v["purpose"] == "qualification" for v in intents) <= 2
    if not allow_unknown:
        assert set(accepted) == set(expected)
    return prep, accepted, unknown, intents, settled, peak


def validate(root=ROOT):
    first = root / "formal-bank"
    second = root / "unattempted-stage-01"
    resolution = root / "explicit-unknown-reissue"
    prep, a, unknown, i, s, peak = stage_facts(first, True)
    nextprep, b, nextunknown, j, t, nextpeak = stage_facts(second, False)
    assert len(unknown) == 1 and not nextunknown
    assert nextprep["stage_lineage"]["parent_preparation_sha256"] == bank.file_hash(first / "preparation.json")
    assert nextprep["stage_lineage"]["parent_ledger_sha256"] == bank.file_hash(first / "collection/attempts.jsonl")
    baseline = live_study.frozen.read_rows(first / "accepted-bank.jsonl")
    assert live_study.frozen.read_rows(second / "accepted-bank.jsonl") == baseline + list(a.values())
    dispatched = {v["pair_key"] for v in i if v["purpose"] == "judgment"}
    assert not dispatched & {v["pair_key"] for v in j if v["purpose"] == "judgment"}
    # Original unknown is accepted only via a separately approved, actually settled new attempt.
    auth = bank.read_json(resolution / "authorization.json")
    assert auth["original_unknown"] == unknown[0] and auth["human_confirmation_reference"]
    newevents = _events(resolution / "attempts.jsonl", bank.file_hash(resolution / "authorization.json"))
    assert len(newevents) == 2 and newevents[0]["kind"] == "intent" and newevents[1]["kind"] == "settled"
    intent = newevents[0]["payload"]
    settlement = newevents[1]["payload"]
    assert intent["pair_key"] == unknown[0]["key"] and intent["purpose"] == "explicitly_authorized_unknown_reissue"
    assert settlement["intent_sequence"] == 0 and settlement["outcome"] == "succeeded"
    record = settlement["bank_entry"]
    row = next(
        r for r in live_study.frozen.read_rows(first / "missing-pairs.jsonl") if live_study.key(r) == intent["pair_key"]
    )
    assert all(record[k] == value for k, value in row.items())
    EngageDecision.model_validate(record["decision"])
    account = ProviderAccounting.model_validate(settlement["accounting"])
    assert (
        account.observed_model_counts == {"gpt-5.6-sol": 1}
        and account.provider_response_count
        == account.successful_decision_count
        == account.usage_complete_response_count
        == 1
        and account.output_tokens <= 256
    )
    record = {
        **record,
        "collection_event_sha256": newevents[1]["sha256"],
        "collected_at_utc": newevents[1]["recorded_at_utc"],
        "explicit_unknown_reissue_authorization_sha256": bank.file_hash(resolution / "authorization.json"),
    }
    records = [*baseline, *a.values(), *b.values(), record]
    assert len(records) == 17520 and len({live_study.key(r) for r in records}) == 17520
    universe = {live_study.key(r): r for r in live_study.frozen.read_rows(root / "preflight-final/inputs.jsonl")}
    assert {live_study.key(r) for r in records} == set(universe)
    for record in records:
        expected = universe[live_study.key(record)]
        assert all(
            record[k] == expected[k]
            for k in ["user_id", "message_id", "client_messages_sha256", "client_condition_sha256"]
        )
    records = sorted(records, key=lambda r: (r["user_id"], r["message_id"], r["client_condition_sha256"]))
    settlements = [*s, *t, settlement]
    intents = [*i, *j, intent]
    result = {
        "schema_version": "ten-topic-gpt-recovered-bank-closure-v1",
        "status": "complete",
        "unique_pairs": 17520,
        "new_successes": len(a) + len(b) + 1,
        "physical_requests": len(intents),
        "qualification_requests": sum(v["purpose"] == "qualification" for v in intents),
        "retry_requests": sum(
            sum(n - 1 for n in Counter(v["pair_key"] for v in group if v["purpose"] == "judgment").values())
            for group in [i, j]
        ),
        "explicit_unknown_reissue_requests": 1,
        "retained_unknown_requests": unknown,
        "maximum_observed_in_flight": max(peak, nextpeak, 1),
        "known_nominal_cost_usd": sum(
            v["subscription_nominal_cost_usd"] for v in settlements if v["subscription_nominal_cost_usd"] is not None
        ),
        "nominal_cost_unknown_attempts": sum(v["subscription_nominal_cost_usd"] is None for v in settlements),
        "actual_incremental_fee": None,
        "production_deploy_eligible": False,
        "verified": True,
        "input_tokens_known_subtotal": sum(v["accounting"]["input_tokens"] or 0 for v in settlements),
        "output_tokens_known_subtotal": sum(v["accounting"]["output_tokens"] or 0 for v in settlements),
        "first_request_utc": bank.read_json(first / "preparation.json").get(
            "first_request_utc",
            _events(first / "collection/attempts.jsonl", bank.file_hash(first / "preparation.json"))[0][
                "recorded_at_utc"
            ],
        ),
        "last_response_utc": max(
            newevents[-1]["recorded_at_utc"],
            _events(second / "collection/attempts.jsonl", bank.file_hash(second / "preparation.json"))[-1][
                "recorded_at_utc"
            ],
        ),
        "total_physical_request_ceiling": None,
        "total_cost_ceiling": None,
        "source_ledgers": [
            {"path": str(p), "sha256": bank.file_hash(p)}
            for p in [
                first / "collection/attempts.jsonl",
                second / "collection/attempts.jsonl",
                resolution / "attempts.jsonl",
            ]
        ],
    }
    for path, digest in bank.read_json(root / "preflight-final/protected-source-hashes.json").items():
        bank.bound(Path(path), digest, "protected historical source")
    final = root / "final-bank"
    if not final.exists():
        final.mkdir()
        _publish(final / "closed-bank.jsonl", records, rows=True)
        _publish(final / "preparation.json", prep, rows=False)
    else:
        assert live_study.frozen.read_rows(final / "closed-bank.jsonl") == records
    result["bank_sha256"] = bank.file_hash(final / "closed-bank.jsonl")
    _publish(final / "closure.json", result, rows=False)
    return result
