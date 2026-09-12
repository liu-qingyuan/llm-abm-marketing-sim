"""Immutable recovery ledger-prefix handoff and its independent consumer."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from . import _concurrent_recovery_replay as _concurrent_replay
from . import concurrent_robustness_formal_execution as _formal
from . import concurrent_robustness_recovery as _proposals
from . import concurrent_robustness_recovery_epoch as _initial
from . import concurrent_robustness_recovery_execution as _execution
from . import concurrent_robustness_v2 as _v2
from ._concurrent_recovery_campaign import RecoveryCampaignError, _owner, _read, _require_scope
from ._concurrent_recovery_progress import CampaignProgress
from ._concurrent_recovery_replay import verify_recovery_realization

BUNDLE_SCHEMA = "concurrent-recovery-execution-bundle-v1"
TASK_BUNDLE_SCHEMA = "concurrent-recovery-task-execution-bundle-v1"


@dataclass(frozen=True)
class _VerifiedRecoveryBundleFacts:
    """Private, independently reconstructed bundle facts for Evidence."""

    bundle_path: Path
    document: dict[str, Any]
    origins: _execution._Origins
    state: CampaignProgress
    records: tuple[dict[str, Any], ...]
    batch_commits: tuple[dict[str, Any], ...]


def _bound_facts(origins: _execution._Origins, records: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    paths = {Path(row["path"]) for row in origins.proposal["source_artifacts"]}
    paths.update((origins.proposal_reference.path, origins.handoff.path))
    handoff = _initial._checked_reference(origins.handoff)
    paths.add(Path(handoff["authorization_artifact"]["path"]))
    if origins.task_plan is None:
        paths.update(Path(row["path"]) for row in handoff["request"]["qualification_artifacts"])
    for row in records:
        if row["kind"] == "epoch_admitted":
            plan = _execution._plan_document(row["payload"]["plan_path"])
            paths.add(Path(plan["plan_path"]))
            if origins.task_plan is None:
                paths.add(Path(plan["authorization_artifact"]["path"]))
                paths.update(Path(ref["path"]) for ref in plan["request"]["qualification_artifacts"])
        elif row["kind"] in {"kimi_manual_retry_accepted", "gpt_manual_retry_accepted", "kimi_retry_policy_accepted", "kimi_cash_cap_amendment_accepted", "final_model_continuation_accepted", "final_model_parallel_accepted"}:
            paths.add(Path(row["payload"]["approval"]["path"]))
        elif row["kind"] == "kimi_official_migration_accepted":
            from ._concurrent_recovery_kimi_migration import receipt_references as migration_references
            paths.update(Path(ref["path"]) for ref in migration_references(row["payload"]["approval"]))
        elif row["kind"] == "gemini_restoration_accepted":
            from ._concurrent_recovery_gemini_restoration import receipt_references as restoration_references
            paths.update(Path(ref["path"]) for ref in restoration_references(row["payload"]))
        elif row["kind"] == "self_check_recheck_accepted":
            from ._concurrent_recovery_recheck import receipt_references
            paths.update(Path(ref["path"]) for ref in receipt_references(row["payload"]))
        elif row["kind"] in {"quota_retry_accepted", "model_lane_accepted", "kimi_output_amendment_accepted"}:
            paths.add(Path(row["payload"]["approval"]["path"]))
        elif row["kind"] == "parallel_execution_accepted":
            from ._concurrent_recovery_parallel import receipt_references as parallel_references
            paths.update(Path(ref["path"]) for ref in parallel_references(row["payload"]))
        elif row["kind"] == "task_revoked":
            paths.add(Path(row["payload"]["revocation"]["path"]))
    return [_proposals._file_fact(path) for path in sorted(paths)]


def _verify_event_origins(origins: _execution._Origins, records: tuple[dict[str, Any], ...]) -> None:
    campaign = origins.campaign
    root = Path(campaign["control_root"])
    if _read(Path(campaign["source_anchor_path"])) != _owner(campaign) or _read(root / "identity.json") != campaign:
        raise RecoveryCampaignError("Recovery bundle source owner differs from its campaign")
    # Future HEAD/appends do not change this immutable original prefix. Never read
    # or hash native runtime files that may have been interrupted mid-write.
    for number, row in enumerate(records, 1):
        original = _read(root / "events" / f"{number:08d}.json")
        if _formal._canonical_json_bytes(original) != _formal._canonical_json_bytes(row):
            raise RecoveryCampaignError("Recovery bundle differs from its immutable event origin")


def _body(path: Path, origins: _execution._Origins, records: tuple[dict[str, Any], ...], state: CampaignProgress,
          facts: list[dict[str, Any]], realization: dict[str, Any]) -> dict[str, Any]:
    prefix = path.parent / "ledger-prefix.jsonl"
    head = records[-1]["record_sha256"] if records else origins.campaign["campaign_identity_sha256"]
    task = origins.task_plan is not None
    return {"schema_version": TASK_BUNDLE_SCHEMA if task else BUNDLE_SCHEMA, "bundle_path": str(path),
            "task_plan" if task else "initial_handoff": origins.handoff.model_dump(mode="json"), "campaign": origins.campaign,
            "head_sha256": head, "ledger_prefix": {"relative_path": prefix.name, "sha256": _formal._sha256_file(prefix),
                                                      "records": len(records), "bytes": prefix.stat().st_size},
            "source_event_origin_policy": "immutable-source-control-events-sequence-v1",
            "artifact_facts": facts, "progress": _execution._progress(origins, state),
            "realization_verification": realization, "formal_evidence_closed": False,
            "production_deploy_eligible": False}


def publish_recovery_bundle(context: _execution._ExecutionContext) -> Path:
    """Publish a create-once checkpoint without dispatch or native-runtime rebind."""
    _require_scope(context.origins.campaign)
    root = context.journal.root / "bundles" / context.journal.head
    target = root / "bundle.json"
    if root.exists():
        checked = read_recovery_bundle(target)
        if checked["head_sha256"] != context.journal.head:
            raise RecoveryCampaignError("Recovery published checkpoint has a crossed head")
        return target
    # Independently reconstruct origins and legal history, not caller summaries.
    origins = _execution._origins(context.origins.handoff)
    records = context.journal.records
    _verify_event_origins(origins, records)
    state = _execution._legal_history(origins, records)
    facts = _bound_facts(origins, records)
    realization = verify_recovery_realization(proposal=origins.proposal, manifest=origins.source.manifest, state=state, records=records)
    if facts != _bound_facts(origins, records):
        raise RecoveryCampaignError("Recovery origins changed during checkpoint verification")
    root.mkdir()
    prefix = root / "ledger-prefix.jsonl"
    with prefix.open("xb") as handle:
        for row in records:
            handle.write(_formal._canonical_json_bytes(row))
        handle.flush()
        os.fsync(handle.fileno())
    prefix.chmod(0o444)
    body = _body(target, origins, records, state, facts, realization)
    _initial._publish_immutable(target, {**body, "bundle_identity_sha256": _v2._json_sha256(body)})
    _v2._fsync_directory(root.parent)
    return target


def _read_verified_recovery_bundle(path: str | Path) -> _VerifiedRecoveryBundleFacts:
    """Verify persisted source origins and return private frozen facts."""
    target = _proposals._safe_path(path)
    fact = _proposals._file_fact(target)
    if cast(int, fact["mode"]) & 0o222:
        raise RecoveryCampaignError("Recovery bundle must be immutable")
    document, _ = _formal._load_canonical_object(target, "recovery bundle")
    if document.get("schema_version") not in {BUNDLE_SCHEMA, TASK_BUNDLE_SCHEMA} or document.get("bundle_path") != str(target):
        raise RecoveryCampaignError("Recovery requires its exact path-bound bundle schema")
    key = "task_plan" if document["schema_version"] == TASK_BUNDLE_SCHEMA else "initial_handoff"
    origins = _execution._origins(_formal.FormalArtifactReference.model_validate(document[key]))
    if (origins.task_plan is not None) != (key == "task_plan"):
        raise RecoveryCampaignError("Recovery bundle authority schema is crossed")
    raw_head = document.get("head_sha256")
    if not isinstance(raw_head, str):
        raise RecoveryCampaignError("Recovery bundle head must be a SHA-256 string")
    head = _v2._require_sha256(raw_head, "recovery bundle head")
    expected_path = Path(origins.campaign["control_root"]) / "bundles" / head / "bundle.json"
    if target != expected_path or {p.name for p in target.parent.iterdir()} != {"bundle.json", "ledger-prefix.jsonl"}:
        raise RecoveryCampaignError("Recovery bundle location or closed inventory is crossed")
    prefix = target.parent / "ledger-prefix.jsonl"
    if cast(int, _proposals._file_fact(prefix)["mode"]) & 0o222:
        raise RecoveryCampaignError("Recovery bundle ledger prefix must be immutable")
    records = tuple(_v2._read_canonical_jsonl(prefix))
    _verify_event_origins(origins, records)
    state = _execution._legal_history(origins, records)
    facts = _bound_facts(origins, records)
    replay = _concurrent_replay._verified_recovery_realization(
        proposal=origins.proposal, manifest=origins.source.manifest,
        state=state, records=records,
    )
    realization = replay.summary
    body = _body(target, origins, records, state, facts, realization)
    expected = {**body, "bundle_identity_sha256": _v2._json_sha256(body)}
    if _formal._canonical_json_bytes(expected) != _formal._canonical_json_bytes(document):
        raise RecoveryCampaignError("Recovery bundle differs from independently verified origins")
    if facts != _bound_facts(origins, records) or hashlib.sha256(target.read_bytes()).hexdigest() != fact["sha256"]:
        raise RecoveryCampaignError("Recovery bundle or origins changed during inspection")
    return _VerifiedRecoveryBundleFacts(
        bundle_path=target, document=expected, origins=origins, state=state,
        records=records, batch_commits=replay.batch_commits,
    )


def read_recovery_bundle(path: str | Path) -> dict[str, Any]:
    """Verify a recovery bundle while preserving the public summary dict."""
    return _read_verified_recovery_bundle(path).document
