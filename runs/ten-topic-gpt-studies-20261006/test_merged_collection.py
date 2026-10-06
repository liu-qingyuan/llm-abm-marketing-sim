import json
from pathlib import Path

import merged_collection as collection
import pytest

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim.decision import ProviderResponseProvenanceUnknown
from llm_abm_sim.provider_accounting import ProviderResponseEnvelope


class Client:
    external_provider_client = False
    last_subscription_nominal_cost_usd = 0.01

    def __init__(self, unknown=False):
        self.calls = 0
        self.unknown = unknown

    def create_response(self, messages, model, **kwargs):
        self.calls += 1
        assert model == "gpt-5.6-sol" and kwargs == {"reasoning_effort": "low", "output_token_ceiling": 256}
        if self.unknown and self.calls == 2:
            raise ProviderResponseProvenanceUnknown("UNIT_TEST_ONLY")
        return ProviderResponseEnvelope(
            decision_text=json.dumps(
                {"engage": True, "probability": 0.5, "confidence": 0.8, "action": "like", "reason": "UNIT_TEST_ONLY"}
            ),
            observed_model="gpt-5.6-sol",
            observed_model_status="reported",
            usage_status="complete",
            input_tokens=100,
            output_tokens=10,
            total_tokens=110,
        )


@pytest.fixture
def prepared(tmp_path):
    source = Path(__file__).parent / "formal-bank"
    root = tmp_path / "UNIT_TEST_ONLY"
    root.mkdir()
    (root / "collection").mkdir()
    prep = bank.read_json(source / "preparation.json")
    prep.update(accepted=0, missing=2, universe=2)
    prep["live_authorization_caps"]["successes"] = 2
    bank.write_json(root / "preparation.json", prep)
    bank.write_jsonl(root / "accepted-bank.jsonl", [])
    bank.write_jsonl(
        root / "missing-pairs.jsonl",
        [json.loads(line) for line in (source / "missing-pairs.jsonl").read_text().splitlines()][:2],
    )
    auth = bank.read_json(source / "execution-authorization.json")
    auth["preparation_sha256"] = bank.file_hash(root / "preparation.json")
    bank.write_json(root / "execution-authorization.json", auth)
    c = bank.read_json(source / "collection/concurrency-authorization.json")
    c["preparation_sha256"] = auth["preparation_sha256"]
    bank.write_json(root / "collection/concurrency-authorization.json", c)
    bank.write_json(
        root / "artifact-manifest.json",
        {
            "schema_version": prep["schema_version"],
            "sha256": {p.name: bank.file_hash(p) for p in root.iterdir() if p.is_file()},
        },
    )
    return root


def test_actual_collection_and_resume(prepared):
    client = Client()
    r = collection.collect(prepared, client)
    assert (r["new_successes"], r["unique_pairs"], r["physical_requests"]) == (2, 2, 3)
    assert client.calls == 3
    again = collection.collect(prepared, client)
    assert again == r and client.calls == 3


def test_unknown_is_terminal_and_never_resent(prepared):
    client = Client(unknown=True)
    with pytest.raises(ValueError, match="stopped"):
        collection.collect(prepared, client)
    assert client.calls == 2
    with pytest.raises(ValueError, match="stopped"):
        collection.collect(prepared, client)
    assert client.calls == 2 and not (prepared / "closed-bank.jsonl").exists()


def test_missing_explicit_approval_stops_before_call(prepared):
    client = Client()
    (prepared / "execution-authorization.json").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        collection.collect(prepared, client)
    assert client.calls == 0
