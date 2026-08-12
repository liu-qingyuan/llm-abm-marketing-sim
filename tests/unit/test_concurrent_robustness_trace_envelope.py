from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json

import pytest

from llm_abm_sim.concurrent_robustness_report import (
    _MAX_TRACE_COMPRESSED_BYTES,
    _MAX_TRACE_UNCOMPRESSED_BYTES,
    _TRACE_ENCODING,
    _TRACE_ENVELOPE_SCHEMA,
    _TRACE_ROW_COUNT,
    _TRACE_RUNTIME_BRIDGE,
    _TRACE_SCRIPT_OPEN,
    _decode_trace_envelope,
    _replace_trace_script,
    _RobustnessReportClosureError,
    _trace_envelope_for_json,
)


def _gzip_bytes(raw: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as stream:
        stream.write(raw)
    return output.getvalue()


def _envelope_for_raw(raw: bytes, *, payload: bytes | None = None) -> dict[str, object]:
    compressed = _gzip_bytes(raw) if payload is None else payload
    return {
        "schema": _TRACE_ENVELOPE_SCHEMA,
        "encoding": _TRACE_ENCODING,
        "uncompressed_byte_length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "row_count": _TRACE_ROW_COUNT,
        "payload": base64.b64encode(compressed).decode("ascii"),
    }


def _trace_row(index: int) -> dict[str, object]:
    return {
        "trace_id": f"trace-{index}",
        "pair_id": f"pair-{index}",
        "message_id": "message_1",
        "message_title": "Message 1",
        "user_id": f"u{index}",
        "latent_class": "class-a",
        "primary_action": "ignore",
        "shadow_action": "ignore",
        "provider_status": "succeeded",
        "time_step": index // 20,
        "ranking_position": (index % 20) + 1,
        "disagreement": False,
    }


def test_trace_envelope_bytes_are_deterministic_and_zero_mtime() -> None:
    trace_json = json.dumps([_trace_row(index) for index in range(1800)], separators=(",", ":"))

    first = _trace_envelope_for_json(trace_json)
    second = _trace_envelope_for_json(trace_json)

    assert first == second
    envelope = json.loads(first)
    compressed = base64.b64decode(envelope["payload"])
    assert compressed[4:8] == b"\x00\x00\x00\x00"
    assert _decode_trace_envelope(envelope) == json.loads(trace_json)


def test_trace_script_replacement_requires_one_exact_marker() -> None:
    trace_json = json.dumps([_trace_row(index) for index in range(1800)], separators=(",", ":"))
    html = f"<main>{_TRACE_SCRIPT_OPEN}{trace_json}</script><p>stable</p></main>"

    replaced = _replace_trace_script(html)

    assert replaced.count(_TRACE_SCRIPT_OPEN) == 1
    assert trace_json not in replaced
    assert replaced.endswith("</main>")
    with pytest.raises(_RobustnessReportClosureError):
        _replace_trace_script("<main>missing</main>")
    with pytest.raises(_RobustnessReportClosureError):
        _replace_trace_script(html.replace("</script>", f"</script>{_TRACE_SCRIPT_OPEN}{trace_json}</script>"))
    with pytest.raises(_RobustnessReportClosureError):
        _replace_trace_script(html.replace(_TRACE_SCRIPT_OPEN, '<script data-testid="run-trace-rows-data">'))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: {**value, "extra": True},
        lambda value: {key: item for key, item in value.items() if key != "payload"},
        lambda value: {**value, "encoding": "json"},
        lambda value: {**value, "uncompressed_byte_length": True},
        lambda value: {**value, "row_count": 1799},
        lambda value: {**value, "sha256": "g" * 64},
        lambda value: {**value, "payload": "not base64"},
    ],
)
def test_trace_envelope_rejects_exact_contract_violations(mutate) -> None:
    value = _envelope_for_raw(b"[]")

    with pytest.raises(ValueError):
        _decode_trace_envelope(mutate(value))


def test_trace_envelope_rejects_compressed_and_uncompressed_limits() -> None:
    oversized_compressed = _envelope_for_raw(b"[]", payload=b"x" * (_MAX_TRACE_COMPRESSED_BYTES + 1))
    with pytest.raises(ValueError, match="compressed"):
        _decode_trace_envelope(oversized_compressed)

    raw = b"x" * (_MAX_TRACE_UNCOMPRESSED_BYTES + 1)
    oversized_uncompressed = _envelope_for_raw(raw)
    with pytest.raises(ValueError, match="uncompressed|decompressed"):
        _decode_trace_envelope(oversized_uncompressed)


def test_trace_envelope_rejects_digest_corruption_and_gzip_corruption() -> None:
    valid = _envelope_for_raw(b'[{"trace_id":"one"}]')
    digest_mismatch = {**valid, "sha256": "0" * 64}
    with pytest.raises(ValueError, match="digest"):
        _decode_trace_envelope(digest_mismatch)

    encoded_payload = valid["payload"]
    assert isinstance(encoded_payload, str)
    compressed = bytearray(base64.b64decode(encoded_payload))
    compressed[12] ^= 1
    corrupt = {**valid, "payload": base64.b64encode(compressed).decode("ascii")}
    with pytest.raises(ValueError):
        _decode_trace_envelope(corrupt)


def test_browser_bridge_consumes_the_gzip_stream_through_the_single_member_boundary() -> None:
    assert "pipeThrough(new DecompressionStream('gzip')).getReader()" in _TRACE_RUNTIME_BRIDGE
    assert "for (;;)" in _TRACE_RUNTIME_BRIDGE
    assert "if (result.done) break" in _TRACE_RUNTIME_BRIDGE
    assert "gzip as exactly one member" in _TRACE_RUNTIME_BRIDGE


def test_trace_envelope_rejects_trailing_and_concatenated_gzip_members() -> None:
    raw = b"[{\"trace_id\":\"one\"}]"
    compressed = _gzip_bytes(raw)
    for payload in (compressed + b"trailing", compressed + _gzip_bytes(raw)):
        value = _envelope_for_raw(raw, payload=payload)
        with pytest.raises(ValueError, match="trailing"):
            _decode_trace_envelope(value)


@pytest.mark.parametrize("raw", [b"\xff", b"not json", b"{}", b"[1]"])
def test_trace_envelope_rejects_invalid_utf8_json_and_row_shape(raw: bytes) -> None:
    value = _envelope_for_raw(raw)

    with pytest.raises(ValueError):
        _decode_trace_envelope(value)
