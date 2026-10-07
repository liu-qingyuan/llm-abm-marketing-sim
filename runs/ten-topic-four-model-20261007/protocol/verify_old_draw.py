#!/usr/bin/env python3
"""Independent old protocol proof; no runtime kernel, Provider or draw helper imports."""
import hashlib
import json
from pathlib import Path
from collections import Counter
ROOT = Path("/Users/liuqingyuan/work/llm-abm-marketing-sim/outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified")
OUT = Path(__file__).resolve().parent

def rows(name):
    return [json.loads(x) for x in (ROOT/name).read_text().splitlines()]

def main():
    judgments = rows("judgments.jsonl")
    terminals = rows("realized_terminals.jsonl")
    bank = {(r["cell_id"], r["user_id"], r["message_id"]): r for r in judgments}
    assert len(bank) == len(judgments) == 28800
    counts = Counter()
    anchors = set()
    observed = Counter()
    for r in terminals:
        j = bank[r["cell_id"], r["user_id"], r["message_id"]]
        for field in ("judgment_id", "provider_engage", "provider_probability", "provider_action", "provider_reason", "provider_confidence", "prompt_canonical_hash", "prompt_version", "requested_model", "observed_model"):
            assert j[field] == r[field], field
        anchor = r["realization_source_identity"]
        anchors.add(anchor)
        assert r["realization_seed"] == 20260823
        assert r["realization_rule_version"] == "sha256-source-user-message-first-53-bits-uniform-v1"
        key = hashlib.sha256(b"\0".join(x.encode() for x in (anchor, r["user_id"], r["message_id"]))).hexdigest()
        assert key == r["realization_key"]
        draw = (int.from_bytes(hashlib.sha256(f"20260823\0{key}".encode()).digest()[:8], "big") >> 11) / (2**53) if j["provider_engage"] else None
        assert draw == r["uniform_draw"]
        positive = draw is not None and draw < j["provider_probability"]
        assert positive == r["realized_engage"]
        assert r["realized_action"] == (j["provider_action"] if positive else "ignore")
        assert r["realization_status"] == ("draw_pass" if positive else "draw_fail" if j["provider_engage"] else "provider_ignore")
        assert j["successful_attempts"][-1]["outcome"] == "succeeded"
        counts[r["cell_id"]] += 1
        observed[(j["requested_model"], j["observed_model"], j["successful_attempts"][-1]["provider_route"])] += 1
    assert len(counts) == 16 and set(counts.values()) == {1800}
    assert len(anchors) == 1
    result = {"schema_version":"ten-topic-four-model-old-draw-proof-v1", "verified_original_pairs":28800, "cells":dict(counts), "source_identity":next(iter(anchors)), "behavior_seed":20260823, "independent_implementation":"stdlib hashlib, raw source judgment/terminal records; no production draw helpers or kernel", "provider_calls":0, "formal_new_paths_executed":0, "source_hashes":{str(ROOT/n):hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ["judgments.jsonl", "realized_terminals.jsonl"]}, "observed_strata_preserved":[{"requested_model":a,"observed_model":b,"route":c,"records":n} for (a,b,c),n in sorted(observed.items())]}
    (OUT/"DRAW_PROOF.json").write_text(json.dumps(result,indent=2))
    print("PASS original_pairs=28800 cells=16 source_anchors=1 provider_calls=0")

if __name__ == "__main__":
    main()
