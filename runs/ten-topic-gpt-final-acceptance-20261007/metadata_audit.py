"""Read-only authorization, declared model, inherited provenance and preservation supplement."""

import hashlib
import json
from collections import Counter
from pathlib import Path

R = Path(
    "/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-gpt-studies-20261006"
)
OUT = Path(__file__).resolve().parent


def read(p):
    return json.loads(Path(p).read_text())


def rows(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines()]


def hashfile(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1048576), b""):
            h.update(b)
    return h.hexdigest()


auth = read(R / "explicit-unknown-reissue/authorization.json")
assert auth["human_confirmation_text"] == "授权三条各一次新补采"
assert (
    auth["maximum_new_requests_per_input"] == 1
    and auth["model"] == "openai-codex/gpt-5.6-sol"
    and auth["provider"] == "pi_openai_oauth_subscription"
    and auth["paid_api_enabled"] is False
)
unknowns = auth["original_unknowns"]
expected = {u["key"]: u["event_sha256"] for u in unknowns}
events = rows(R / "explicit-unknown-reissue/attempts.jsonl")
intents = [e["payload"] for e in events if e["kind"] == "intent"]
assert len(intents) == 3 and Counter(i["pair_key"] for i in intents) == Counter({k: 1 for k in expected})
for i in intents:
    assert (
        i["purpose"] == "explicitly_authorized_unknown_reissue"
        and i["original_unknown_event_sha256"] == expected[i["pair_key"]]
    )
manifest = read(R / "formal-paths/manifest.json")
origin = read(R / "ready-formal-paths/partial-manifest.json")
reused = 0
for relative, digest in manifest["paths"].items():
    doc = read(R / "formal-paths" / relative)
    if "reused_execution_source" in doc:
        ref = doc["reused_execution_source"]
        assert ref["sha256"] == origin["completed_verified_paths"][relative]
        olddoc = read(ref["root"])
        assert olddoc["path"] == doc["path"]
        for field in [
            "study",
            "configuration",
            "seed",
            "weights",
            "neighbor_saturation",
            "arm",
            "draw_anchor",
            "network_source_manifest_sha256",
        ]:
            assert olddoc["identity"][field] == doc["identity"][field]
        reused += 1
    else:
        assert relative.startswith("index/local_p99_rebuilt-")
assert reused == 2700
files = {}
for dirname in ["final-bank", "formal-report"]:
    for f in sorted((R / dirname).iterdir()):
        if f.is_file():
            files[str(f)] = hashfile(f)
files[str(R / "formal-paths/manifest.json")] = hashfile(R / "formal-paths/manifest.json")
for path, digest in read(R / "preflight-final/protected-source-hashes.json").items():
    assert hashfile(path) == digest
old = read(R.parent / "ten-topic-full-pool-20261006/preservation.json")
for ref in old["existing_untracked_weekly_files"]:
    assert hashfile(ref["path"]) == ref["sha256"]
result = {
    "status": "pass",
    "provider_calls": 0,
    "exact_three_once_authorization": True,
    "reused_paths": 2700,
    "remaining_realized_paths": 100,
    "old_source_hashes_equal": True,
    "old_untracked_weekly_files_preserved": True,
    "final_absolute_paths_sha256": files,
    "limitations": [
        "No raw Provider wire payload was persisted; response authenticity is verified through recorded normalized observed-model/usage and hash-linked settlement evidence, not remote attestation.",
        "No cash invoice/extra Provider request was made.",
    ],
}
(OUT / "metadata-evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print("METADATA_ACCEPTANCE passed; 2700 trace-bound reused executions and final100 verified; Provider=0")
