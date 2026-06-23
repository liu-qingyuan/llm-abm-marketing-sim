from __future__ import annotations

import json
from pathlib import Path

from llm_abm_sim.data_sources.douyin_collector import DouyinCollector, DouyinCollectRequest
from llm_abm_sim.data_sources.tikhub_client import TikHubClient, TikHubSettings, redact_secrets


def test_redact_secrets_nested_values() -> None:
    data = {"Authorization": "Bearer secret-token", "nested": {"cookie": "abc", "value": "secret-token"}}
    text = repr(redact_secrets(data, ["secret-token"]))
    assert "secret-token" not in text
    assert "Bearer secret-token" not in text
    assert "abc" not in text


def test_redact_secrets_stringified_header_fields() -> None:
    text = '{"headers":{"Authorization":"Bearer secret-token","Cookie":"session=abc"},"message":"failed"}'
    redacted = redact_secrets(text, ["secret-token"])
    assert "secret-token" not in redacted
    assert "session=abc" not in redacted
    assert "Bearer" not in redacted


def test_redact_secrets_plain_and_repr_header_strings() -> None:
    samples = [
        "Authorization: Bearer secret-token",
        "Cookie: session=abc; other=def",
        "{'Authorization': 'Bearer secret-token'}",
        "headers\\nAuthorization: Bearer secret-token\\nCookie: session=abc; other=def\\nbody",
    ]
    for sample in samples:
        redacted = redact_secrets(sample, ["secret-token"])
        assert "secret-token" not in redacted
        assert "session=abc" not in redacted
        assert "other=def" not in redacted
        assert "Bearer" not in redacted


def test_collector_artifacts_do_not_leak_secret(tmp_path: Path) -> None:
    def transport(method, url, headers, params, json_body, timeout):
        if "fetch_topic_query" in url:
            return {"challenge_id": "cha"}
        if "fetch_challenge_posts" in url:
            return {"videos": []}
        return {}

    settings = TikHubSettings(api_key="secret-token", qps=1000)
    collector = DouyinCollector(TikHubClient(settings, transport=transport), settings)
    paths = collector.collect(DouyinCollectRequest(run_id="run", output_root=tmp_path, mode="mock"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths["raw_dir"].glob("*") if path.is_file())
    combined += json.dumps(json.loads(paths["report"].read_text(encoding="utf-8")))
    assert "secret-token" not in combined
    assert "Bearer secret-token" not in combined
    assert "authorization" not in combined.lower()
    assert "cookie" not in combined.lower()
