"""Only the approved GPT subscription transport, five independent clients."""
import json
from contextlib import ExitStack
from pathlib import Path
import merged_collection
from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim.providers.pi_subscription import PiSubscriptionProviderClient

root=Path(__file__).resolve().parent/'unattempted-stage-02'
prep=merged_collection._load(root)
for name,digest in prep['implementation_hashes'].items():bank.bound(root.parent/name,digest,'frozen implementation')
try:
    with ExitStack() as stack:
        clients=[stack.enter_context(PiSubscriptionProviderClient(response_timeout_seconds=30.0)) for _ in range(5)]
        print('Pi subscription workers ready; GPT-only qualification and collection starting',flush=True)
        result=merged_collection.collect(root,clients)
        print(json.dumps(result,sort_keys=True),flush=True)
except BaseException as exc:
    ledger=root/'collection/attempts.jsonl'
    events=merged_collection._events(ledger,bank.file_hash(root/'preparation.json')) if ledger.exists() else []
    result={'status':'partial','exception_type':type(exc).__name__,'physical_requests':sum(e['kind']=='intent' for e in events),'settled_attempts':sum(e['kind']=='settled' for e in events),'new_successes':sum(e['kind']=='settled' and e['payload'].get('outcome')=='succeeded' and 'user_id' in e['payload'].get('bank_entry',{}) for e in events)}
    bank.write_json(root/'collection/partial.json',result)
    print(json.dumps(result,sort_keys=True),flush=True)
    raise SystemExit(1) from None
