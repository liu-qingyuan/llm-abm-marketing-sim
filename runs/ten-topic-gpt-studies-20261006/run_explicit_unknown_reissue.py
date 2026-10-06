"""Run only after a separately recorded human authorization for the exact three unknowns."""

import fcntl
from contextlib import ExitStack
from pathlib import Path

import bank_union
import live_study
import merged_collection
import offline_path_engine
import unknown_diagnostics

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_collection import _append, _events
from llm_abm_sim.concurrent_message_experiment import _prepare_concurrent_runtime_inputs
from llm_abm_sim.decision import ProviderDecisionError
from llm_abm_sim.providers.pi_subscription import PiSubscriptionProviderClient
from llm_abm_sim.providers.robustness import PiOpenAIDecisionAdapter

ROOT = Path(__file__).resolve().parent


def run():
    resolution = ROOT / "explicit-unknown-reissue"
    # No directory creation or transport construction before actual human confirmation exists.
    auth = bank.read_json(resolution / "authorization.json")
    unknowns = []
    input_rows = {}
    for name in ["formal-bank", "unattempted-stage-01", "unattempted-stage-02", "unattempted-stage-03"]:
        p = ROOT / name
        f = bank_union.stage_facts(p, name != "unattempted-stage-03")
        unknowns += f[2]
        input_rows.update({live_study.key(r): r for r in live_study.frozen.read_rows(p / "missing-pairs.jsonl")})
    if (
        auth["schema_version"] != "ten-topic-three-unknown-explicit-reissue-authorization-v1"
        or auth["original_unknowns"] != unknowns
        or len(unknowns) != 3
        or not auth["human_confirmation_reference"]
        or auth["maximum_new_requests_per_input"] != 1
        or auth["model"] != "openai-codex/gpt-5.6-sol"
        or auth["paid_api_enabled"] is not False
    ):
        raise ValueError("explicit unknown-specific approval differs")
    identity = bank.file_hash(resolution / "authorization.json")
    ledger = resolution / "attempts.jsonl"
    events = _events(ledger, identity)
    pending = {}
    completed = set()
    attempted = set()
    for event in events:
        v = event["payload"]
        if event["kind"] == "intent":
            pending[event["sequence"]] = v
            attempted.add(v["pair_key"])
        else:
            intent = pending.pop(v["intent_sequence"])
            if v["outcome"] != "succeeded":
                raise ValueError("explicit new attempt not succeeded; no automatic resend")
            completed.add(intent["pair_key"])
    if pending:
        raise ValueError("unsettled explicit request; no automatic resend")
    prep = merged_collection._load(ROOT / "formal-bank")
    cfg, _, source = bank._inputs(bank.read_json(Path(prep["audit"]["path"])))
    cfg = cfg.model_copy(update={"network_scope": "final_collected_topics"})
    base = _prepare_concurrent_runtime_inputs(cfg)
    with (resolution / "writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with ExitStack() as stack:
            client = stack.enter_context(PiSubscriptionProviderClient(response_timeout_seconds=30.0))
            merged_collection._validate_transport(prep, client)
            for unresolved in unknowns:
                key = unresolved["key"]
                if key in completed:
                    continue
                if key in attempted:
                    raise ValueError("new explicit request already attempted")
                row = input_rows[key]
                prepared, _ = live_study.arm_inputs(cfg, base, row["arm"])
                data = offline_path_engine.decision_input(
                    cfg, prepared, prep["request_condition"], row["user_id"], row["message_id"]
                )
                if bank.client_identity(data, prep["request_condition"]) != (
                    row["client_messages_sha256"],
                    row["client_condition_sha256"],
                ):
                    raise ValueError("explicit request input changed")
                adapter = PiOpenAIDecisionAdapter(
                    prompt_version=prep["request_condition"]["prompt_version"], client=client
                )
                intent = {
                    "intent_sequence": len(events),
                    "pair_key": key,
                    "purpose": "explicitly_authorized_unknown_reissue",
                    "client_condition_sha256": row["client_condition_sha256"],
                    "original_unknown_event_sha256": unresolved["event_sha256"],
                }
                _append(ledger, events, identity, "intent", intent)
                attempted.add(key)
                result = {"intent_sequence": intent["intent_sequence"]}
                try:
                    d = adapter.decide(
                        data.post, data.profile, data.peer_context, data.platform_context, data.time_step
                    )
                    result.update(
                        outcome="succeeded",
                        bank_entry={
                            **row,
                            "decision": d.model_dump(mode="json"),
                            "source": "explicitly-authorized-unknown-new-request",
                            "acceptance_policy": "preserved-original-unknown-new-observed-judgment-v1",
                        },
                    )
                except ProviderDecisionError as exc:
                    result.update(outcome="failed_explicit_request", failure_category=exc.failure_category)
                except BaseException as exc:
                    result.update(
                        outcome="unknown",
                        failure_category="response_provenance_unknown",
                        unknown_transport_case=unknown_diagnostics.classify(exc),
                    )
                result["accounting"] = adapter.provider_accounting.model_dump(mode="json")
                result["subscription_nominal_cost_usd"] = adapter.last_subscription_nominal_cost_usd
                result["actual_incremental_fee"] = None
                _append(ledger, events, identity, "settled", result)
                print({"key": key, "new_request_outcome": result["outcome"]}, flush=True)
                if result["outcome"] != "succeeded":
                    raise ValueError("explicit single attempt stopped; no automatic retry")
        bank.v2._assert_source_unchanged(source)
    return bank_union.validate(ROOT)


if __name__ == "__main__":
    print(run())
