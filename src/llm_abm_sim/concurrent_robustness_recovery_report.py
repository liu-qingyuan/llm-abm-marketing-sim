"""Independent recovered-study reports; no Provider, authorization or deployment."""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from . import concurrent_robustness_recovery as _paths
from . import concurrent_robustness_recovery_epoch as _immutable
from . import concurrent_robustness_v2_report as _presentation
from .concurrent_robustness_recovery_evidence import (
    ClosedRecoveryEvidence,
    close_concurrent_robustness_recovery_evidence,
    read_concurrent_robustness_recovery_evidence,
    summarize_recovery_attempt_usage,
)
from .concurrent_robustness_v2 import _V2_MODELS, _V2AttemptEvidence
from .concurrent_robustness_v2_evidence import _fee_summary
from .providers.robustness import robustness_provider_disclosures

REPORT_MANIFEST_SCHEMA = "concurrent-recovery-report-manifest-v1"


class RecoveryReportError(ValueError):
    """Recovery report origins, projection or publication did not close."""


def _reference(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": _presentation._sha256_file(path)}


def _usage_columns(attempts: Sequence[_V2AttemptEvidence]) -> dict[str, Any]:
    summary = summarize_recovery_attempt_usage(attempts)
    return {"input_tokens": summary["input_usage"], "output_tokens": summary["output_usage"],
            "total_tokens": summary["total_usage"], "cached_input_tokens": summary["cached_input_usage"]}


def _judgment_row(
    rows: Sequence[Mapping[str, Any]], attempts: Sequence[_V2AttemptEvidence],
) -> dict[str, Any]:
    actions = Counter(row["provider_action"] for row in rows)
    count = len(rows)
    positive = sum(actions[action] for action in _presentation._POSITIVE_ACTIONS)
    return {
        "provider_like_count": actions["like"], "provider_comment_count": actions["comment"],
        "provider_share_count": actions["share"], "provider_ignore_count": actions["ignore"],
        "positive_judgment_count": positive, "logical_judgment_count": count,
        "positive_judgment_rate": round(positive / count, 12) if count else 0.0,
        "mean_probability": round(sum(row["provider_probability"] for row in rows) / count, 12) if count else 0.0,
        "mean_confidence": round(sum(row["provider_confidence"] for row in rows) / count, 12) if count else 0.0,
        "terminal_failure_count": 0,  # Final judgments, not historical failed attempts.
        "physical_attempt_count": len(attempts),
        "retry_attempt_count": sum(a.outcome == "retryable_failure" for a in attempts),
        "provider_response_count": sum(a.provider_response_count for a in attempts),
        "usage_complete_judgment_count": count, "usage_missing_judgment_count": 0,
        **_usage_columns(attempts),
        "requested_model_counts": _presentation._compact_json(dict(Counter(row["requested_model"] for row in rows))),
        "observed_model_counts": _presentation._compact_json(dict(Counter(row["observed_model"] for row in rows))),
        "provider_route_counts": _presentation._compact_json(dict(Counter(a.provider_route for a in attempts))),
        "billing_semantics_counts": _presentation._compact_json(dict(Counter(a.billing_semantics for a in attempts))),
        **_fee_summary(attempts),
    }


def _provider_rows(
    source: ClosedRecoveryEvidence, attempts_by_model: Mapping[str, list[_V2AttemptEvidence]],
) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for disclosure in robustness_provider_disclosures():
        model = str(disclosure["requested_model"])
        attempts = attempts_by_model.get(model, [])
        judgments = [row for row in source.final_judgments if row["requested_model"] == model]
        observed = Counter(row["observed_model"] for row in judgments)
        required = disclosure["required_observed_model"]
        route = disclosure["provider_route"]
        if observed != {required: 7200} or any(a.provider_route != route for a in attempts):
            raise RecoveryReportError("Recovery Provider identities or routes differ from closed evidence")
        rows.append({
            "execution_profile": "formal", "condition_evidence_scope": "independently_closed_recovery_evidence",
            "requested_model": model, "required_observed_model": required,
            "observed_model_counts": _presentation._compact_json(dict(observed)),
            "planned_provider_route": route,
            "observed_provider_route_counts": _presentation._compact_json(dict(Counter(a.provider_route for a in attempts))),
            "planned_route_kind": disclosure["route_kind"], "planned_wire_model": disclosure["wire_model"],
            "planned_wire_api": disclosure["wire_api"], "planned_reasoning_effort": disclosure["reasoning_effort"],
            "planned_thinking_mode": disclosure["thinking_mode"],
            "planned_output_token_ceiling": disclosure["output_token_ceiling"],
            "planned_billing_semantics": disclosure["billing_semantics"],
            "observed_billing_semantics_counts": _presentation._compact_json(dict(Counter(a.billing_semantics for a in attempts))),
            "planned_billing_currency": disclosure["billing_currency"], "planned_fee_ceiling": disclosure["fee_ceiling"],
            "persisted_request_contract": _presentation._compact_json(source.manifest.request_contract.model_dump(mode="json")),
            "physical_attempt_count": len(attempts), "terminal_failure_count": 0, **_usage_columns(attempts),
            "gateway_context_visibility": disclosure["gateway_context_visibility"],
            "direct_gemini_developer_api": disclosure["direct_gemini_developer_api"],
            "client_prompt_scope": disclosure["client_prompt_scope"],
        })
    return tuple(rows)


def _build_recovery_projection(source: ClosedRecoveryEvidence) -> _presentation._ValidatedReportProjection:
    """Project only newly closed recovery facts, never an emulated v2 source."""
    if source.document.get("formal_evidence_closed") is not True:
        raise RecoveryReportError("Recovery report requires independently closed Formal evidence")
    membership = source.membership_by_user
    judgments: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    realized: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    grouped_attempts: dict[tuple[str, str, str, str], list[_V2AttemptEvidence]] = defaultdict(list)
    model_attempts: dict[str, list[_V2AttemptEvidence]] = defaultdict(list)
    for row in source.final_judgments:
        judgments[row["requested_model"], row["prompt_variant"], membership[row["user_id"]], row["message_id"]].append(row)
    for terminal in source.terminals:
        realized[terminal.requested_model, terminal.prompt_variant, membership[terminal.user_id], terminal.message_id][terminal.realized_action] += 1
    all_attempts: list[_V2AttemptEvidence] = []
    for row in source.attempts:
        attempt = _V2AttemptEvidence.model_validate(row["attempt"])
        grouped_attempts[row["requested_model"], row["prompt_variant"], membership[row["user_id"]], row["message_id"]].append(attempt)
        model_attempts[row["requested_model"]].append(attempt)
        all_attempts.append(attempt)
    main_rows: list[Mapping[str, Any]] = []
    audit_rows: list[Mapping[str, Any]] = []
    for model in _V2_MODELS:
        for prompt in _presentation._PROMPTS:
            for segment in _presentation._SEGMENTS:
                for message_id in source.manifest.message_ids:
                    key = model, prompt, segment, message_id
                    dimensions = {"model": model, "prompt": prompt, "segment": segment,
                                  "message": _presentation._MESSAGE_LABELS[message_id], "prompt_anchor": f"#prompt-catalog-{prompt}"}
                    actions = realized.get(key, Counter())
                    exposures = sum(actions.values())
                    positive = sum(actions[action] for action in _presentation._POSITIVE_ACTIONS)
                    main_rows.append({**dimensions, "like_count": actions["like"], "comment_count": actions["comment"],
                                      "share_count": actions["share"], "engagement_count": positive, "exposure_count": exposures,
                                      "engagement_rate": round(positive / exposures, 12) if exposures else 0.0})
                    audit_rows.append({**dimensions, **_judgment_row(judgments.get(key, []), grouped_attempts.get(key, []))})
    if (sum(row["exposure_count"] for row in main_rows) != 36000
            or sum(row["logical_judgment_count"] for row in audit_rows) != 36000
            or len(all_attempts) != source.document["counts"]["physical_attempts"]):
        raise RecoveryReportError("Recovery report denominators differ from final evidence")
    providers = _provider_rows(source, model_attempts)
    messages = _presentation._normalized_message_catalog(source.manifest, source.messages)
    prompts = _presentation._prompt_catalog(providers, messages)
    mechanism = _presentation._MECHANISM_PRESENTATION.build_robustness_v2_master()
    accounting = {key: dict(source.document[key]) for key in
                  ("counts", "all_attempt_usage", "successful_sequence_usage", "fees")}
    accounting["counts"]["failed_attempts_retained"] = sum(a.outcome != "succeeded" for a in all_attempts)
    lineage = {"scope": "independently_closed_recovery_evidence",
               "recovery_evidence": _reference(source.evidence_path),
               "recovery_evidence_manifest": _reference(source.evidence_path.parent / "artifact_manifest.json"),
               "recovery_bundle": dict(source.document["source_bundle"])}
    return _presentation._ValidatedReportProjection(
        source_lineage=lineage,
        formal_topology={"cells": 20, "logical_judgments_per_cell": 1800, "logical_judgments": 36000,
                         "maximum_physical_attempts": 108000},
        realized_denominator={"cells": 20, "logical_judgments_per_cell": 1800, "logical_judgments": 36000, "exposures": 36000},
        realized_main_rows=tuple(main_rows), judgment_audit_rows=tuple(audit_rows), prompt_catalog=prompts,
        message_catalog=messages, provider_audit_rows=providers,
        cell_batch_evidence_rows=_presentation._normalized_cell_batch_rows(source.manifest, source.batch_commits),
        claim_boundary={"fixed_sample": True, "fixed_graph": True, "shared_deterministic_draw": True,
                        "one_realized_path_per_cell": True, "historical_cells_in_realized_main": False,
                        "provider_reason_scope": "judgment_only", "invented_realized_explanation": False,
                        "winner_claim": False, "accuracy_or_calibration_claim": False,
                        "causal_or_external_validity_claim": False, "all_attempt_usage_complete": False,
                        "successful_sequence_usage_complete": True, "self_checks_in_formal_denominator": False},
        mechanism_schema_version=mechanism.schema_version,
        mechanism_identity_sha256=mechanism.semantic_set_identity_sha256,
        recovery_accounting=accounting,
    )


def _payloads(source: ClosedRecoveryEvidence) -> tuple[dict[str, bytes], dict[str, str]]:
    projection = _build_recovery_projection(source)
    payloads = _presentation._new_artifact_payloads(projection)
    downloads = _presentation._download_mapping("")
    downloads.update(recovery_accounting_csv=_presentation._RECOVERY_ACCOUNTING_CSV,
                     recovery_evidence_json="evidence/evidence.json",
                     recovery_evidence_manifest="evidence/artifact_manifest.json")
    payloads[_presentation._REPORT_PAYLOAD] = _presentation._canonical_json_bytes(
        _presentation._report_payload_document(projection, downloads=downloads))
    payloads["report.html"] = _presentation._render_recovery_html(projection, downloads)
    return payloads, downloads


def _manifest(root: Path, source: ClosedRecoveryEvidence, payloads: Mapping[str, bytes], downloads: Mapping[str, str]) -> dict[str, Any]:
    evidence_hashes, evidence_sizes = _presentation._tree_records(source.evidence_path.parent)
    hashes = {f"evidence/{name}": digest for name, digest in evidence_hashes.items()}
    sizes = {f"evidence/{name}": size for name, size in evidence_sizes.items()}
    hashes.update({name: _presentation._sha256_bytes(body) for name, body in payloads.items()})
    sizes.update({name: len(body) for name, body in payloads.items()})
    body = {"schema_version": REPORT_MANIFEST_SCHEMA, "output_root": str(root),
            "source_evidence": _reference(source.evidence_path),
            "source_bundle": dict(source.document["source_bundle"]),
            "artifacts": [{"relative_path": name, "sha256": hashes[name], "bytes": sizes[name]} for name in sorted(hashes)],
            "approved_downloads": dict(downloads), "counts": dict(source.document["counts"]),
            "formal_evidence_closed": True, "report_status": "complete", "production_deploy_eligible": False,
            "provider_calls_during_composition": 0, "canonical_deployment_triggered": False}
    return {**body, "report_identity_sha256": _presentation._sha256_bytes(_presentation._canonical_json_bytes(body))}


def _check_file(path: Path, expected: bytes) -> None:
    fact = _paths._file_fact(path)
    if cast(int, fact["mode"]) & 0o222 or path.read_bytes() != expected:
        raise RecoveryReportError("Recovery report file differs from its immutable expected bytes")


def _publish_file(path: Path, payload: bytes) -> None:
    if os.path.lexists(path):
        _check_file(path, payload)
        return
    # The final manifest is the atomic closure marker. An interrupted individual
    # write is an explicit incomplete artifact, never overwritten as a repair.
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), 0o444)


def _validate_report(root: Path, source: ClosedRecoveryEvidence) -> dict[str, Any]:
    if source.evidence_path != root / "evidence/evidence.json":
        raise RecoveryReportError("Recovery report borrowed another evidence root")
    payloads, downloads = _payloads(source)
    manifest = _manifest(root, source, payloads, downloads)
    expected_paths = {row["relative_path"] for row in manifest["artifacts"]} | {"artifact_manifest.json"}
    hashes, _ = _presentation._tree_records(root)
    if ({p.name for p in root.iterdir()} != set(payloads) | {"evidence", "artifact_manifest.json"}
            or set(hashes) != expected_paths):
        raise RecoveryReportError("Recovery report closed inventory is crossed")
    for name, payload in payloads.items():
        _check_file(root / name, payload)
    _check_file(root / "artifact_manifest.json", _presentation._canonical_json_bytes(manifest))
    return manifest


def inspect_concurrent_robustness_recovery_report(report_path: str | Path) -> dict[str, Any]:
    """Independent reconstruction; never trust a report's Formal-closure flag."""
    path = _paths._safe_path(Path(report_path))
    if path.name != "report.html":
        raise RecoveryReportError("Recovery inspection requires an explicit report.html")
    source = read_concurrent_robustness_recovery_evidence(path.parent / "evidence/evidence.json")
    return _validate_report(path.parent, source)


def export_concurrent_robustness_recovery_report(bundle_path: str | Path, *, output_dir: str | Path) -> Path:
    """Close evidence first, then same-source exports; report-only retry is free of Provider calls."""
    root = _paths._safe_path(Path(output_dir))
    evidence_path = root / "evidence/evidence.json"
    if root.exists() and (not root.is_dir() or not evidence_path.is_file()):
        raise RecoveryReportError("Recovery report workspace is a foreign or incomplete collision")
    closed = close_concurrent_robustness_recovery_evidence(bundle_path, output_dir=root / "evidence")
    if closed != evidence_path:
        raise RecoveryReportError("Evidence publication returned a crossed output identity")
    source = read_concurrent_robustness_recovery_evidence(closed)
    payloads, downloads = _payloads(source)
    if {p.name for p in root.iterdir()} - (set(payloads) | {"evidence", "artifact_manifest.json"}):
        raise RecoveryReportError("Recovery report workspace contains foreign files")
    if (root / "artifact_manifest.json").exists():
        _validate_report(root, source)
        return root / "report.html"
    for name, payload in payloads.items():
        _publish_file(root / name, payload)
    manifest = _manifest(root, source, payloads, downloads)
    _immutable._publish_immutable(root / "artifact_manifest.json", manifest)
    inspect_concurrent_robustness_recovery_report(root / "report.html")
    return root / "report.html"
