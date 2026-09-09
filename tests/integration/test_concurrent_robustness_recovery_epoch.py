from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal
from llm_abm_sim import concurrent_robustness_operator as operator
from llm_abm_sim import concurrent_robustness_recovery as proposals
from llm_abm_sim import concurrent_robustness_recovery_epoch as epoch
from tests.integration.test_concurrent_robustness_recovery import (
    _stopped_plan,
)
from tests.integration.test_concurrent_robustness_recovery import (
    recovery_source as recovery_source,
)
from tests.unit.test_concurrent_robustness_formal_execution import _NOW


def _write(path: Path, document: dict[str, Any]) -> str:
    if path.exists():
        path.chmod(0o644)
    payload = formal._canonical_json_bytes(document)
    path.write_bytes(payload)
    path.chmod(0o444)
    return hashlib.sha256(payload).hexdigest()


def _request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: Path,
) -> tuple[epoch.RecoveryInitialEpochRequest, Path]:
    # Only source classification and Provider transports are synthetic. These
    # fixtures are not genuine qualifications/approval or new Formal evidence.
    old_plan, _ = _stopped_plan(tmp_path, monkeypatch, source)
    proposals.prepare_concurrent_robustness_recovery(old_plan, output_dir=tmp_path / "campaign")
    proposal_path = tmp_path / "campaign/recovery-proposal.json"
    contracts = tmp_path / "epoch-1"
    contracts.mkdir()
    old_request = formal._request_from_plan(json.loads(old_plan.read_bytes())["request"])
    references = []
    for index, old in enumerate(old_request.qualification_artifacts):
        document = json.loads(old.path.read_bytes())
        document.update(
            qualification_reference=f"fixture:initial-epoch-{index}",
            qualified_at_utc=(_NOW + timedelta(days=2, hours=-1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires_at_utc=(_NOW + timedelta(days=2, hours=23)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        path = contracts / f"qualification-{index}.json"
        digest = _write(path, document)
        # Existing qualification Interface binds canonical bytes, not POSIX
        # write bits. Real historical qualifications are owner-only 0600.
        path.chmod(0o600)
        references.append(formal.FormalQualificationArtifactReference(
            requested_model=old.requested_model, path=path, sha256=digest,
        ))
    return epoch.RecoveryInitialEpochRequest(
        proposal=formal.FormalArtifactReference(
            path=proposal_path, sha256=hashlib.sha256(proposal_path.read_bytes()).hexdigest(),
        ),
        qualification_artifacts=tuple(references),
    ), old_plan


def _approval(request: epoch.RecoveryInitialEpochRequest, destination: Path) -> tuple[Path, str]:
    authorization = epoch.prepare_recovery_initial_epoch(request)["authorization_template"]
    authorization.update(
        authorization_reference="fixture:explicit-initial-recovery-253",
        approved_at_utc=(_NOW + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        expires_at_utc=(_NOW + timedelta(days=2, hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    digest = _write(destination, authorization)
    destination.chmod(0o600)
    return destination, digest


def _inventory(root: Path) -> dict[str, tuple[str, int]]:
    return {str(path): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode)
            for path in root.rglob("*") if path.is_file()}


def test_initial_epoch_readiness_is_zero_write_and_does_not_renew_original_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    request, _ = _request(tmp_path, monkeypatch, recovery_source)
    before = _inventory(tmp_path)
    readiness = epoch.prepare_recovery_initial_epoch(request)
    identity = readiness["request_identity"]
    assert readiness["status"] == "ready_for_human" and readiness["execution_authority"] is False
    assert identity["remaining_valid_judgments"] == 35_999
    assert identity["maximum_new_physical_attempts"] == 35_998 * 3 + 2
    assert identity["maximum_new_physical_attempts"] != 108_000
    assert identity["epoch_ordinal"] == 1 and identity["requested_model"] == "deepseek-v4-flash"
    assert len(identity["qualification_artifacts"]) == 5
    assert readiness["provider_calls"] == readiness["credential_reads"] == readiness["recovery_slots_consumed"] == 0
    assert readiness["authorization_template"]["authorization_reference"].startswith("REPLACE-")
    assert not Path(identity["campaign"]["source_anchor_path"]).exists()
    assert _inventory(tmp_path) == before


def test_initial_handoff_is_immutable_revalidated_after_expiry_and_rejected_by_the_old_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    request, _ = _request(tmp_path, monkeypatch, recovery_source)
    authorization_path, digest = _approval(request, tmp_path / "epoch-1/authorization.json")
    destination = tmp_path / "epoch-1/plan.json"
    before = _inventory(tmp_path)
    plan = epoch.authorize_recovery_initial_epoch(
        request=request, authorization_path=authorization_path,
        authorization_sha256=digest, plan_output=destination,
    )
    inspected = epoch.inspect_recovery_initial_epoch_plan(destination)
    assert inspected["plan_identity_sha256"] == plan["plan_identity_sha256"]
    assert inspected["current_gate"]["currently_valid"] is True
    assert plan["execution_authority"] is False and plan["initial_epoch_only"] is True
    assert not destination.stat().st_mode & 0o222
    assert {key: value for key, value in _inventory(tmp_path).items() if key != str(destination)} == before
    with pytest.raises(ValueError):
        epoch.authorize_recovery_initial_epoch(
            request=request, authorization_path=authorization_path,
            authorization_sha256=digest, plan_output=destination,
        )
    with pytest.raises(ValueError):
        operator.run_concurrent_robustness_formal(destination)
    monkeypatch.setattr(formal, "_utc_now", lambda: _NOW + timedelta(days=4))
    after = _inventory(tmp_path)
    inspected = epoch.inspect_recovery_initial_epoch_plan(destination)
    assert inspected["current_gate"]["currently_valid"] is False
    assert inspected["current_gate"]["authorization_current"] is False
    assert all(not row["currently_valid"] for row in inspected["current_gate"]["qualifications"])
    assert _inventory(tmp_path) == after
    with pytest.raises(ValueError):
        epoch.prepare_recovery_initial_epoch(request)


@pytest.mark.parametrize("corruption", ["budget", "authority", "origin", "head", "location"])
def test_initial_handoff_rejects_rehashed_caller_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, corruption: str,
) -> None:
    request, _ = _request(tmp_path, monkeypatch, recovery_source)
    auth_path, digest = _approval(request, tmp_path / "epoch-1/authorization.json")
    path = tmp_path / "epoch-1/plan.json"
    plan = epoch.authorize_recovery_initial_epoch(
        request=request, authorization_path=auth_path, authorization_sha256=digest, plan_output=path,
    )
    if corruption == "authority":
        plan["execution_authority"] = True
    elif corruption == "origin":
        plan["authorization"]["request_identity"]["campaign"]["historical_failed_pair"]["stopped_record_sha256"] = "f" * 64
    elif corruption == "head":
        plan["authorization"]["request_identity"]["expected_head_sha256"] = "f" * 64
    elif corruption == "budget":
        plan["authorization"]["request_identity"]["maximum_new_physical_attempts"] = 108_000
    elif corruption == "location":
        path = path.with_name("copied-plan.json")
    if corruption in {"budget", "origin", "head"}:
        # Re-hash every self-reported layer, not just the enclosing plan. The
        # consumer must still derive the truth from immutable parent origins.
        plan["authorization"]["request_identity_sha256"] = epoch._v2._json_sha256(
            plan["authorization"]["request_identity"]
        )
        plan["authorization_artifact"]["sha256"] = _write(auth_path, plan["authorization"])
    plan["plan_identity_sha256"] = epoch._v2._json_sha256(
        {key: value for key, value in plan.items() if key != "plan_identity_sha256"}
    )
    _write(path, plan)
    with pytest.raises(ValueError):
        epoch.inspect_recovery_initial_epoch_plan(path)


@pytest.mark.parametrize("location", ["control", "anchor"])
def test_initial_handoff_consumer_rejects_rehashed_copy_in_protected_campaign_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, location: str,
) -> None:
    request, _ = _request(tmp_path, monkeypatch, recovery_source)
    auth_path, digest = _approval(request, tmp_path / "epoch-1/authorization.json")
    path = tmp_path / "epoch-1/plan.json"
    plan = epoch.authorize_recovery_initial_epoch(
        request=request, authorization_path=auth_path, authorization_sha256=digest, plan_output=path,
    )
    campaign = plan["authorization"]["request_identity"]["campaign"]
    if location == "control":
        target = Path(campaign["control_root"]) / "copied-plan.json"
        target.parent.mkdir()
    else:
        target = Path(campaign["source_anchor_path"])
    plan["plan_path"] = str(target)
    plan["plan_identity_sha256"] = epoch._v2._json_sha256(
        {key: value for key, value in plan.items() if key != "plan_identity_sha256"}
    )
    _write(target, plan)
    before = _inventory(tmp_path)
    with pytest.raises(ValueError):
        epoch.inspect_recovery_initial_epoch_plan(target)
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("corruption", ["missing_model", "boolean_coercion", "expired", "too_long", "symlink"])
def test_initial_epoch_rejects_invalid_independent_qualifications_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, corruption: str,
) -> None:
    request, _ = _request(tmp_path, monkeypatch, recovery_source)
    if corruption == "missing_model":
        with pytest.raises(ValueError):
            epoch.RecoveryInitialEpochRequest(proposal=request.proposal, qualification_artifacts=request.qualification_artifacts[:-1])
        return
    reference = request.qualification_artifacts[0]
    document = json.loads(reference.path.read_bytes())
    if corruption == "boolean_coercion":
        document["usage_complete"] = 1
    elif corruption == "expired":
        document["qualified_at_utc"] = _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
        document["expires_at_utc"] = (_NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif corruption == "too_long":
        document["expires_at_utc"] = (_NOW + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = _write(reference.path, document)
    if corruption == "symlink":
        target = reference.path.with_name("symlink-target.json")
        reference.path.rename(target)
        reference.path.symlink_to(target)
    changed = formal.FormalQualificationArtifactReference(
        requested_model=reference.requested_model, path=reference.path, sha256=digest,
    )
    request = epoch.RecoveryInitialEpochRequest(
        proposal=request.proposal, qualification_artifacts=(changed, *request.qualification_artifacts[1:]),
    )
    before = _inventory(tmp_path)
    with pytest.raises(ValueError):
        epoch.prepare_recovery_initial_epoch(request)
    assert _inventory(tmp_path) == before


def test_source_anchor_is_stable_across_proposals_and_cannot_be_claimed_during_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    request, old_plan = _request(tmp_path, monkeypatch, recovery_source)
    first = epoch.prepare_recovery_initial_epoch(request)["request_identity"]["campaign"]
    second_root = tmp_path / "alternate-campaign"
    proposals.prepare_concurrent_robustness_recovery(old_plan, output_dir=second_root)
    path = second_root / "recovery-proposal.json"
    second_request = epoch.RecoveryInitialEpochRequest(
        proposal=formal.FormalArtifactReference(path=path, sha256=hashlib.sha256(path.read_bytes()).hexdigest()),
        qualification_artifacts=request.qualification_artifacts,
    )
    second = epoch.prepare_recovery_initial_epoch(second_request)["request_identity"]["campaign"]
    assert first["control_root"] != second["control_root"]
    assert first["source_anchor_path"] == second["source_anchor_path"]
    copied_plan_root = tmp_path / "copied-source-plan"
    copied_plan_root.mkdir()
    copied_plan = copied_plan_root / "plan.json"
    copied_plan.write_bytes(old_plan.read_bytes())
    copied_plan.chmod(0o444)
    third_root = tmp_path / "third-campaign"
    proposals.prepare_concurrent_robustness_recovery(copied_plan, output_dir=third_root)
    third_path = third_root / "recovery-proposal.json"
    third = epoch.prepare_recovery_initial_epoch(epoch.RecoveryInitialEpochRequest(
        proposal=formal.FormalArtifactReference(path=third_path, sha256=hashlib.sha256(third_path.read_bytes()).hexdigest()),
        qualification_artifacts=request.qualification_artifacts,
    ))["request_identity"]["campaign"]
    assert third["source_anchor_path"] == first["source_anchor_path"]
    anchor = Path(first["source_anchor_path"])
    anchor.write_bytes(b"existing owner; do not interpret as unused")
    for item in (request, second_request):
        with pytest.raises(ValueError):
            epoch.prepare_recovery_initial_epoch(item)
    assert anchor.read_bytes() == b"existing owner; do not interpret as unused"


def test_initial_plan_install_collision_does_not_overwrite_or_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    request, _ = _request(tmp_path, monkeypatch, recovery_source)
    auth_path, digest = _approval(request, tmp_path / "epoch-1/authorization.json")
    target = tmp_path / "epoch-1/plan.json"
    original_link = os.link

    def collide(source: Any, destination: Any, **kwargs: Any) -> None:
        Path(destination).write_bytes(b"foreign artifact")
        original_link(source, destination, **kwargs)

    monkeypatch.setattr(os, "link", collide)
    with pytest.raises(FileExistsError):
        epoch.authorize_recovery_initial_epoch(
            request=request, authorization_path=auth_path, authorization_sha256=digest, plan_output=target,
        )
    assert target.read_bytes() == b"foreign artifact"
    assert (target.parent / ".plan.json.pending").is_file()
    with pytest.raises(ValueError):
        epoch.inspect_recovery_initial_epoch_plan(target)


def test_initial_epoch_cli_roundtrip_never_reaches_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import run_concurrent_robustness_v2 as cli

    request, _ = _request(tmp_path, monkeypatch, recovery_source)
    request_path = tmp_path / "epoch-1/request.json"
    _write(request_path, request.model_dump(mode="json"))
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    assert cli.main(["prepare-recovery-epoch", "--request", str(request_path)]) == 0
    readiness = json.loads(capsys.readouterr().out)
    assert readiness["execution_authority"] is False
    assert readiness["provider_calls"] == readiness["credential_reads"] == 0
    auth_path, digest = _approval(request, tmp_path / "epoch-1/authorization.json")
    plan = tmp_path / "epoch-1/plan.json"
    assert cli.main([
        "authorize-recovery-epoch", "--request", str(request_path), "--authorization", str(auth_path),
        "--authorization-sha256", digest, "--plan-output", str(plan),
    ]) == 0
    published = json.loads(capsys.readouterr().out)
    assert published["initial_epoch_only"] is True and published["execution_authority"] is False
    assert cli.main(["inspect-recovery-epoch", "--plan", str(plan)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified_initial_handoff"
    assert cli.main(["run", "--plan", str(plan)]) == 1
    assert json.loads(capsys.readouterr().out)["category"] == "operator_error"
    dangerous = tmp_path / "credentials.json"
    dangerous.write_text('{"api_key":"sensitive-test-only"}')
    original_open = Path.open

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        assert path != dangerous, "credential filename must be rejected before a read"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    assert cli.main(["prepare-recovery-epoch", "--request", str(dangerous)]) == 1
    error = capsys.readouterr().out
    assert "sensitive-test-only" not in error
    assert json.loads(error)["category"] == "recovery_epoch_invalid"


@pytest.mark.parametrize("corruption", ["placeholder", "too_long", "backdated", "protected_destination"])
def test_initial_epoch_rejects_invalid_approval_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, corruption: str,
) -> None:
    request, old_plan = _request(tmp_path, monkeypatch, recovery_source)
    auth_path, _ = _approval(request, tmp_path / "epoch-1/authorization.json")
    authorization = json.loads(auth_path.read_bytes())
    target = tmp_path / "epoch-1/plan.json"
    if corruption == "placeholder":
        authorization["authorization_reference"] = "REPLACE-WITH-INDEPENDENT-OPERATIONAL-ISSUE"
    elif corruption == "too_long":
        authorization["expires_at_utc"] = (_NOW + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif corruption == "backdated":
        authorization["approved_at_utc"] = (_NOW + timedelta(days=2, hours=-2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        target = old_plan.parent / "must-not-write.json"
    digest = _write(auth_path, authorization)
    before = _inventory(tmp_path)
    with pytest.raises(ValueError):
        epoch.authorize_recovery_initial_epoch(
            request=request, authorization_path=auth_path, authorization_sha256=digest, plan_output=target,
        )
    assert not target.exists()
    assert _inventory(tmp_path) == before
