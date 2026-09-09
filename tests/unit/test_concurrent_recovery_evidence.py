from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_abm_sim import concurrent_robustness_v2 as v2
from llm_abm_sim.concurrent_robustness_recovery_evidence import (
    RecoveryEvidenceError,
    _file_sha,
    _read_json,
    _read_jsonl,
    _safe_output_dir,
    close_concurrent_robustness_recovery_evidence,
    summarize_recovery_attempt_usage,
)


def _attempt(number: int, *, missing: bool = False) -> v2._V2AttemptEvidence:
    return v2._V2AttemptEvidence.model_validate({
        "schema_version": "concurrent-robustness-provider-attempt-v2",
        "attempt_number": number,
        "outcome": "nonretryable_failure" if missing else "succeeded",
        "failure_category": "usage_evidence" if missing else None,
        "status_code": None,
        "wait_source": None,
        "wait_seconds": None,
        "lane_cooldown": False,
        "request_invocations": 1,
        "provider_response_count": 1,
        "successful_decision_count": 0 if missing else 1,
        "observed_model_counts": {"deepseek-v4-flash": 1},
        "observed_model_missing_response_count": 0,
        "observed_model_malformed_response_count": 0,
        "usage_complete_response_count": 0 if missing else 1,
        "usage_missing_response_count": 1 if missing else 0,
        "usage_malformed_response_count": 0,
        "input_usage": None if missing else 20,
        "output_usage": None if missing else 10,
        "total_usage": None if missing else 30,
        "cached_input_usage": None if missing else 0,
        "provider_route": "deepseek_official",
        "billing_semantics": "provider_fee_cny",
        "billing_currency": "CNY",
        "provider_fee_cny": None,
        "subscription_nominal_cost_usd": None,
        "fee_ceiling": None,
    })


def test_usage_summary_keeps_known_subtotals_and_nullable_totals() -> None:
    summary = summarize_recovery_attempt_usage((_attempt(1), _attempt(2, missing=True)))

    assert summary["provider_response_count"] == 2
    assert summary["usage_complete_response_count"] == 1
    assert summary["usage_missing_response_count"] == 1
    assert summary["usage_malformed_response_count"] == 0
    assert summary["input_usage"] is None
    assert summary["input_usage_known_subtotal"] == 20
    assert summary["output_usage"] is None
    assert summary["total_usage_known_subtotal"] == 30
    assert summary["cached_input_usage"] is None


def test_empty_usage_summary_has_null_tokens_not_zero() -> None:
    summary = summarize_recovery_attempt_usage(())

    assert summary["input_usage"] is None
    assert summary["input_usage_known_subtotal"] is None
    assert summary["provider_response_count"] == 0


def test_closer_rejects_incomplete_bundle_before_creating_report_workspace(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.json"
    bundle.write_bytes(json.dumps({"schema_version": "not-a-recovery-bundle"}, separators=(",", ":")).encode())
    output = tmp_path / "report" / "evidence"

    with pytest.raises(RecoveryEvidenceError):
        close_concurrent_robustness_recovery_evidence(bundle, output_dir=output)

    assert not output.exists()
    assert not output.parent.exists()


def test_output_preflight_allows_one_missing_immediate_parent(tmp_path: Path) -> None:
    output = tmp_path / "report" / "evidence"

    assert _safe_output_dir(output) == output
    assert not output.exists()
    assert not output.parent.exists()


@pytest.mark.parametrize("reader", [_read_json, _read_jsonl])
def test_new_evidence_readers_reject_writable_files(tmp_path: Path, reader: object) -> None:
    path = tmp_path / "payload.json"
    path.write_text("{}\n")
    path.chmod(0o644)
    with pytest.raises(RecoveryEvidenceError, match="immutable"):
        reader(path, "test payload")  # type: ignore[operator]


def test_origin_hash_guard_rejects_credentials_before_content_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / ".env"
    path.write_text("synthetic forbidden input; never read")
    original = Path.open
    opened: list[Path] = []
    def guarded(self: Path, *args: object, **kwargs: object) -> object:
        if self == path:
            opened.append(self)
            raise AssertionError("Credential content read before path guard")
        return original(self, *args, **kwargs)  # type: ignore[arg-type]
    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        _file_sha(path)
    assert opened == []
