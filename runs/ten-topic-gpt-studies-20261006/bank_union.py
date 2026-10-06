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
    stages = [
        root / "formal-bank",
        root / "unattempted-stage-01",
        root / "unattempted-stage-02",
        root / "unattempted-stage-03",
    ]
    facts = [stage_facts(p, index < len(stages) - 1) for index, p in enumerate(stages)]
    prep = facts[0][0]
    baseline = live_study.frozen.read_rows(stages[0] / "accepted-bank.jsonl")
    records = list(baseline)
    unknowns = []
    intents = []
    settlements = []
    peaks = []
    dispatched = set()
    for index, (stage, fact) in enumerate(zip(stages, facts, strict=True)):
        local, accepted, unknown, requests, responses, peak = fact
        if index:
            assert local["stage_lineage"]["parent_preparation_sha256"] == bank.file_hash(
                stages[index - 1] / "preparation.json"
            )
            assert local["stage_lineage"]["parent_ledger_sha256"] == bank.file_hash(
                stages[index - 1] / "collection/attempts.jsonl"
            )
        assert live_study.frozen.read_rows(stage / "accepted-bank.jsonl") == records
        keys = {v["pair_key"] for v in requests if v["purpose"] == "judgment"}
        assert not keys & dispatched
        dispatched.update(keys)
        records += list(accepted.values())
        unknowns += unknown
        intents += requests
        settlements += responses
        peaks.append(peak)
    assert len(unknowns) == 3 and len(records) == 17517
    resolution = root / "explicit-unknown-reissue"
    auth = bank.read_json(resolution / "authorization.json")
    assert auth["original_unknowns"] == unknowns and auth["human_confirmation_reference"]
    events = _events(resolution / "attempts.jsonl", bank.file_hash(resolution / "authorization.json"))
    expected_unknown = {r["key"]: r for r in unknowns}
    pending = {}
    resolved = {}
    reissue_intents = []
    expected_inputs = {
        live_study.key(r): r for stage in stages for r in live_study.frozen.read_rows(stage / "missing-pairs.jsonl")
    }
    for ordinal, event in enumerate(events):
        assert event["sequence"] == ordinal
        v = event["payload"]
        if event["kind"] == "intent":
            assert v["purpose"] == "explicitly_authorized_unknown_reissue" and v["pair_key"] in expected_unknown
            assert v["pair_key"] not in resolved and not any(i["pair_key"] == v["pair_key"] for i in pending.values())
            assert v["intent_sequence"] == ordinal
            pending[ordinal] = v
            reissue_intents.append(v)
        else:
            assert event["kind"] == "settled"
            intent = pending.pop(v["intent_sequence"])
            assert v["outcome"] == "succeeded"
            record = v["bank_entry"]
            key = live_study.key(record)
            assert key == intent["pair_key"] and all(record[k] == value for k, value in expected_inputs[key].items())
            EngageDecision.model_validate(record["decision"])
            a = ProviderAccounting.model_validate(v["accounting"])
            assert (
                a.observed_model_counts == {"gpt-5.6-sol": 1}
                and a.provider_response_count == a.successful_decision_count == a.usage_complete_response_count == 1
                and a.output_tokens <= 256
            )
            resolved[key] = {
                **record,
                "collection_event_sha256": event["sha256"],
                "collected_at_utc": event["recorded_at_utc"],
                "explicit_unknown_reissue_authorization_sha256": bank.file_hash(resolution / "authorization.json"),
            }
            settlements.append(v)
    assert not pending and set(resolved) == set(expected_unknown) and len(reissue_intents) == 3
    intents += reissue_intents
    records += list(resolved.values())
    universe = {live_study.key(r): r for r in live_study.frozen.read_rows(root / "preflight-final/inputs.jsonl")}
    assert len(records) == 17520 and {live_study.key(r) for r in records} == set(universe)
    for record in records:
        expected = universe[live_study.key(record)]
        assert all(
            record[k] == expected[k]
            for k in ["user_id", "message_id", "client_messages_sha256", "client_condition_sha256"]
        )
    records = sorted(records, key=lambda r: (r["user_id"], r["message_id"], r["client_condition_sha256"]))
    ledgers = [p / "collection/attempts.jsonl" for p in stages] + [resolution / "attempts.jsonl"]
    stamps = [
        _events(p, bank.file_hash(stage / "preparation.json")) for p, stage in zip(ledgers[:-1], stages, strict=True)
    ]
    result = {
        "schema_version": "ten-topic-gpt-recovered-bank-closure-v1",
        "status": "complete",
        "unique_pairs": 17520,
        "new_successes": len(records) - len(baseline),
        "physical_requests": len(intents),
        "qualification_requests": sum(v["purpose"] == "qualification" for v in intents),
        "retry_requests": sum(
            sum(n - 1 for n in Counter(v["pair_key"] for v in f[3] if v["purpose"] == "judgment").values())
            for f in facts
        ),
        "explicit_unknown_reissue_requests": 3,
        "retained_unknown_requests": unknowns,
        "maximum_observed_in_flight": max(peaks),
        "known_nominal_cost_usd": sum(
            v["subscription_nominal_cost_usd"] for v in settlements if v["subscription_nominal_cost_usd"] is not None
        ),
        "nominal_cost_unknown_attempts": sum(v["subscription_nominal_cost_usd"] is None for v in settlements),
        "actual_incremental_fee": None,
        "production_deploy_eligible": False,
        "verified": True,
        "input_tokens_known_subtotal": sum(v["accounting"]["input_tokens"] or 0 for v in settlements),
        "output_tokens_known_subtotal": sum(v["accounting"]["output_tokens"] or 0 for v in settlements),
        "first_request_utc": stamps[0][0]["recorded_at_utc"],
        "last_response_utc": max([e[-1]["recorded_at_utc"] for e in stamps] + [events[-1]["recorded_at_utc"]]),
        "total_physical_request_ceiling": None,
        "total_cost_ceiling": None,
        "source_ledgers": [{"path": str(p), "sha256": bank.file_hash(p)} for p in ledgers],
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
