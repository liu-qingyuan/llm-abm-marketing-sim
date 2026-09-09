"""Shared rendering only: these tiny projection rows are not Formal evidence."""
from __future__ import annotations

import csv
import io
from typing import Any

from openpyxl import load_workbook

from llm_abm_sim import concurrent_robustness_v2_report as presentation


def test_recovery_accounting_has_explicit_schema_and_nullable_same_source_exports() -> None:
    # Isolate the already-validated projection/renderer seam, not Evidence closure.
    realized: dict[str, Any] = dict.fromkeys(presentation._REALIZED_FIELDS, 0)
    realized.update(model="deepseek-v4-flash", prompt="P0", segment="S1", message="M1",
                    prompt_anchor="#prompt-catalog-P0")
    judgment: dict[str, Any] = dict.fromkeys(presentation._JUDGMENT_FIELDS, 0)
    judgment.update(model="deepseek-v4-flash", prompt="P0", segment="S1", message="M1",
                    prompt_anchor="#prompt-catalog-P0", total_tokens=None, input_tokens=None)
    audit = {"counts": {"logical_judgments": 1, "physical_attempts": 2, "self_check_attempts": 1},
             "all_attempt_usage": {"total_usage": None, "total_usage_known_subtotal": 12,
                                   "usage_missing_response_count": 1},
             "successful_sequence_usage": {"total_usage": 12},
             "fees": {"provider_fee_cny": None}}
    projection = presentation._ValidatedReportProjection(
        source_lineage={"scope": "tiny_rendering_fixture_not_formal"},
        formal_topology={}, realized_denominator={"logical_judgments": 1},
        realized_main_rows=(realized,), judgment_audit_rows=(judgment,),
        prompt_catalog=(), message_catalog=(), provider_audit_rows=(),
        cell_batch_evidence_rows=(), claim_boundary={"fixture_only": True},
        mechanism_schema_version="fixture", mechanism_identity_sha256="a" * 64,
        recovery_accounting=audit,
    )
    doc = projection.document()
    assert doc["schema_version"] == "concurrent-recovery-report-projection-v1"
    assert doc["recovery_accounting"] == audit
    rows = presentation._recovery_accounting_rows(projection)
    encoded = presentation._csv_bytes(presentation._RECOVERY_ACCOUNTING_FIELDS, rows)
    csv_rows = list(csv.DictReader(io.StringIO(encoded.decode())))
    total = next(row for row in csv_rows if row["scope"] == "all_attempt_usage" and row["metric"] == "total_usage")
    assert total["value"] == ""
    subtotal = next(row for row in csv_rows if row["metric"] == "total_usage_known_subtotal")
    assert subtotal["value"] == "12"
    workbook_bytes = presentation._workbook_bytes(projection)
    presentation._validate_workbook(workbook_bytes, projection)
    workbook = load_workbook(io.BytesIO(workbook_bytes), data_only=True)
    try:
        values = list(workbook["Recovery Accounting"].values)
        assert ("all_attempt_usage", "total_usage", None) in values
        assert ("all_attempt_usage", "total_usage_known_subtotal", 12) in values
    finally:
        workbook.close()
    markup = presentation._recovery_accounting_html(projection)
    assert "recovery-accounting" in markup and "unknown" in markup.lower()
    assert ">None<" not in presentation._judgment_panels(projection)
