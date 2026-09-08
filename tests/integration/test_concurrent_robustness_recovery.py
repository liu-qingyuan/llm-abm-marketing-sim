from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal
from llm_abm_sim import concurrent_robustness_operator as operator
from llm_abm_sim import concurrent_robustness_v2 as v2
from scripts import run_concurrent_robustness_v2 as cli
from tests.integration.test_concurrent_message_experiment_runner import _make_validation_report_source
from tests.integration.test_concurrent_robustness_v2 import _v2_manifest
from tests.unit.test_concurrent_robustness_formal_execution import _NOW, _authorization_artifact, _request_bundle
from tests.unit.test_concurrent_robustness_operator import _clients


@pytest.fixture(scope="module")
def recovery_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("recovery-validation-source")
    return _make_validation_report_source(root, "source", report_sized=True)


def _stopped_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: Path, *, failure: str = "usage_evidence",
    successful_prefix: int = 1,
) -> tuple[Path, Path]:
    """Synthetic provenance, NOT real Formal evidence or a deployable fixture.

    Only Provider transports and the source's Validation/Formal classification
    boundary are substituted. Real plan/expiry/hash, scheduling and persistence
    run with production-sized denominators; recovery itself stays entirely offline.
    """
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    request, _ = _request_bundle(contracts)
    validation = _v2_manifest(source, output_identity=request.output_identity)
    manifest = validation.model_copy(update={
        "source": validation.source.model_copy(update={"kind": "formal"}),
        "execution_profile": "formal",
        "request_contract": validation.request_contract.model_copy(update={
            "timeout_seconds": 30.0, "retry_backoff_seconds": 1.0,
        }),
    })
    payload = v2._manifest_bytes(manifest)
    request.manifest.path.write_bytes(payload)
    request = request.model_copy(update={
        "manifest": request.manifest.model_copy(update={"sha256": hashlib.sha256(payload).hexdigest()}),
    })
    monkeypatch.setattr(formal, "_utc_now", lambda: _NOW)
    authorization, digest, _ = _authorization_artifact(contracts, request)
    plan = contracts / "plan.json"
    formal.authorize_formal_execution(
        request=request, authorization_path=authorization, authorization_sha256=digest,
        plan_output=plan,
    )
    monkeypatch.setattr(v2, "_validate_source_against_manifest", lambda *_args: None)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    created = _clients(monkeypatch)
    factory = operator._OpenAISDKClient

    def missing_usage_factory(**settings: Any) -> Any:
        client: Any = factory(**settings)
        original_call = client.create_response

        def respond(*args: Any, **kwargs: Any) -> Any:
            response = original_call(*args, **kwargs)
            if len(client.calls) > successful_prefix:
                if failure == "unknown":
                    from llm_abm_sim.decision import ProviderResponseProvenanceUnknown
                    raise ProviderResponseProvenanceUnknown("synthetic unknown")
                if failure in {"quota_exhausted", "exhausted"}:
                    from llm_abm_sim.providers.robustness import ProviderAttemptFailure
                    raise ProviderAttemptFailure(
                        category="quota_exhausted" if failure == "quota_exhausted" else "rate_limited",
                        retryable=failure == "exhausted", status_code=429,
                        wait_seconds=0.0 if failure == "exhausted" else None,
                        wait_source="retry_after" if failure == "exhausted" else None,
                        lane_cooldown=failure == "exhausted",
                    )
                return response.model_copy(update={
                    "usage_status": "missing", "input_tokens": None, "output_tokens": None,
                    "total_tokens": None, "cached_input_tokens": None,
                })
            return response

        client.create_response = respond
        return client

    monkeypatch.setattr(operator, "_OpenAISDKClient", missing_usage_factory)
    result = operator.run_concurrent_robustness_formal(plan)
    assert result.status == ("reconciliation_required" if failure == "unknown" else "stopped")
    expected_calls = successful_prefix + (3 if failure == "exhausted" else 1)
    assert result.physical_provider_attempts == expected_calls
    assert len(created[0].calls) == expected_calls and all(not client.calls for client in created[1:])
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM")
    monkeypatch.setattr(formal, "_utc_now", lambda: _NOW + timedelta(days=2))

    def denied(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("recovery proposal must not execute Study, set up clients or read credentials")

    monkeypatch.setattr(operator, "_runtime_credential", denied)
    monkeypatch.setattr(operator, "_new_client", denied)
    monkeypatch.setattr(operator.ConcurrentRobustnessStudy, "run", denied)
    return plan, request.output_root


def _inventory(*roots: Path) -> dict[str, tuple[str, int]]:
    return {
        str(path): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode)
        for root in roots for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("successful_prefix", [1, 61])
def test_prepare_recovery_binds_stopped_prefix_without_authority_or_parent_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    recovery_source: Path, successful_prefix: int,
) -> None:
    plan, workspace = _stopped_plan(tmp_path, monkeypatch, recovery_source, successful_prefix=successful_prefix)
    before = _inventory(tmp_path, recovery_source)
    output = tmp_path / "new-campaign"

    assert cli.main(["prepare-recovery", "--plan", str(plan), "--output-dir", str(output)]) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "ready_for_human"
    proposal_path = output / "recovery-proposal.json"
    proposal = json.loads(proposal_path.read_text())
    assert proposal["execution_authority"] is False
    assert proposal["provider_calls_during_preparation"] == proposal["credential_reads_during_preparation"] == 0
    assert proposal["source_plan"]["sha256"] == hashlib.sha256(plan.read_bytes()).hexdigest()
    assert proposal["output_identity"] == "new-campaign"
    assert proposal["source_output_root"] == str(workspace)
    assert proposal["progress"]["successful_judgments"] == successful_prefix
    assert proposal["progress"]["failed_logical_judgments"] == 1
    assert proposal["progress"]["physical_attempts"] == successful_prefix + 1
    assert proposal["remaining_valid_judgments"] == 36_000 - successful_prefix
    assert proposal["maximum_new_physical_attempts"] == (35_999 - successful_prefix) * 3 + 2
    assert proposal["inherited_cells"][0]["completed_batches"] == successful_prefix // 60
    assert proposal["failed_pair"]["remaining_attempt_budget"] == 2
    assert proposal["current_gate_at_preparation"]["authorization_status"] == "expired"
    assert all(row["status"] == "expired" for row in proposal["current_gate_at_preparation"]["qualifications"])
    assert proposal_path.stat().st_mode & 0o222 == 0
    after = _inventory(tmp_path, recovery_source)
    assert all(after[path] == facts for path, facts in before.items())
    assert {Path(path) for path in after.keys() - before.keys()} == {proposal_path}
    assert not (workspace / "two_stage_execution").exists()
    assert cli.main(["inspect-recovery", "--proposal", str(proposal_path)]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["execution_authority"] is False and checked["current_gate"]["currently_valid"] is False
    assert checked["proposal_identity_sha256"] == proposal["proposal_identity_sha256"]
    assert _inventory(tmp_path, recovery_source) == after
    assert cli.main(["check-plan", "--plan", str(proposal_path)]) != 0
    capsys.readouterr()
    assert _inventory(tmp_path, recovery_source) == after


@pytest.mark.parametrize("corruption", ["missing", "leading"])
def test_recovery_rejects_invalid_runtime_status_without_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, corruption: str,
) -> None:
    from llm_abm_sim.concurrent_execution_journal import (
        CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON,
        derive_concurrent_execution_workspace,
    )

    plan, workspace = _stopped_plan(tmp_path, monkeypatch, recovery_source)
    scope = v2._operational_root(workspace) / "cell-00"
    status = derive_concurrent_execution_workspace(scope / "runtime") / CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON
    if corruption == "missing":
        status.unlink()
    else:
        document = json.loads(status.read_text())
        document["closed_pair_count"] += 1
        status.write_bytes(v2._canonical_json_bytes(document).rstrip(b"\n"))
    before = _inventory(tmp_path)
    output = tmp_path / "new-campaign"
    assert cli.main(["prepare-recovery", "--plan", str(plan), "--output-dir", str(output)]) != 0
    assert not output.exists() and _inventory(tmp_path) == before


@pytest.mark.parametrize("failure", ["unknown", "quota_exhausted", "exhausted"])
def test_recovery_does_not_reinterpret_other_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, failure: str,
) -> None:
    plan, _ = _stopped_plan(tmp_path, monkeypatch, recovery_source, failure=failure)
    before = _inventory(tmp_path)
    output = tmp_path / "new-campaign"
    assert cli.main(["prepare-recovery", "--plan", str(plan), "--output-dir", str(output)]) != 0
    assert not output.exists() and _inventory(tmp_path) == before


@pytest.mark.parametrize("tamper", ["budget", "origin", "authority", "source_mode"])
def test_proposal_consumer_recomputes_facts_instead_of_trusting_rehashed_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, tamper: str,
) -> None:
    from llm_abm_sim.concurrent_robustness_recovery import prepare_concurrent_robustness_recovery

    plan, _ = _stopped_plan(tmp_path, monkeypatch, recovery_source)
    output = tmp_path / "new-campaign"
    document = cast(dict[str, Any], prepare_concurrent_robustness_recovery(plan, output_dir=output))
    proposal = output / "recovery-proposal.json"
    if tamper == "source_mode":
        plan.chmod(0o644)
    else:
        if tamper == "budget":
            document["maximum_new_physical_attempts"] += 1
        elif tamper == "origin":
            document["inherited_cells"][0]["inherited_pairs"] = []
        else:
            document["execution_authority"] = True
        document.pop("proposal_identity_sha256")
        document["proposal_identity_sha256"] = v2._json_sha256(document)
        proposal.chmod(0o644)
        proposal.write_bytes(v2._canonical_json_bytes(document))
        proposal.chmod(0o444)
    before = _inventory(tmp_path)
    assert cli.main(["inspect-recovery", "--proposal", str(proposal)]) != 0
    assert _inventory(tmp_path) == before


def test_recovery_guards_dataset_symlink_before_configuration_reads_users(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    plan, _ = _stopped_plan(tmp_path, monkeypatch, recovery_source)
    config = v2._close_source(recovery_source).source_evidence.config_snapshot
    users = Path(str(config["dataset_dir"])) / "users.csv"
    retained = users.with_name("users-retained.csv")
    users.rename(retained)
    users.symlink_to(retained)

    def no_configuration_read(*_args: object) -> Any:
        pytest.fail("dataset path guard must precede the configuration's users.csv reader")

    monkeypatch.setattr(v2, "_dynamic_runtime_config", no_configuration_read)
    output = tmp_path / "new-campaign"
    try:
        assert cli.main(["prepare-recovery", "--plan", str(plan), "--output-dir", str(output)]) != 0
        assert not output.exists() and users.is_symlink()
    finally:
        users.unlink()
        retained.rename(users)


def test_prepare_never_overwrites_existing_or_aliased_destinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    plan, workspace = _stopped_plan(tmp_path, monkeypatch, recovery_source)
    existing = tmp_path / "existing-target"
    existing.mkdir()
    (existing / "report.html").write_text("unrelated immutable report")
    alias = tmp_path / "aliased-target"
    alias.symlink_to(existing, target_is_directory=True)
    before = _inventory(tmp_path)
    for target in (workspace, v2._operational_root(workspace), plan.parent, existing, alias):
        assert cli.main(["prepare-recovery", "--plan", str(plan), "--output-dir", str(target)]) != 0
    assert _inventory(tmp_path) == before and alias.is_symlink()


def test_proposal_install_race_preserves_foreign_target_and_never_reports_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    from llm_abm_sim import concurrent_robustness_recovery as recovery

    plan, _ = _stopped_plan(tmp_path, monkeypatch, recovery_source)
    output = tmp_path / "new-campaign"
    before = _inventory(tmp_path)

    def collision(_source: Path, destination: Path, **_kwargs: object) -> None:
        destination.write_bytes(b"foreign target must survive")
        raise FileExistsError("synthetic install collision")

    monkeypatch.setattr(recovery.os, "link", collision)
    assert cli.main(["prepare-recovery", "--plan", str(plan), "--output-dir", str(output)]) != 0
    assert (output / "recovery-proposal.json").read_bytes() == b"foreign target must survive"
    assert (output / ".recovery-proposal.pending").is_file()
    after = _inventory(tmp_path)
    assert all(after[path] == facts for path, facts in before.items())
    assert cli.main(["inspect-recovery", "--proposal", str(output / "recovery-proposal.json")]) != 0


@pytest.mark.parametrize("corruption", ["duplicate_ledger", "truncated_ledger", "snapshot_escape", "spool"])
def test_prepare_rejects_corrupt_persisted_history_without_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, corruption: str,
) -> None:
    from llm_abm_sim.concurrent_execution_journal import (
        CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL,
        derive_concurrent_execution_workspace,
    )

    plan, workspace = _stopped_plan(
        tmp_path, monkeypatch, recovery_source, successful_prefix=61 if corruption == "spool" else 1,
    )
    cell = v2._operational_root(workspace) / "cell-00"
    runtime = derive_concurrent_execution_workspace(cell / "runtime")
    ledger = cell / "pair_lifecycle.jsonl"
    if corruption == "duplicate_ledger":
        payload = ledger.read_bytes()
        ledger.write_bytes(payload + payload.splitlines(keepends=True)[-1])
    elif corruption == "truncated_ledger":
        ledger.write_bytes(ledger.read_bytes()[:-3])
    elif corruption == "snapshot_escape":
        journal = runtime / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL
        records = [json.loads(row) for row in journal.read_text().splitlines()]
        next(row for row in records if row["record_type"] == "snapshot")["snapshot_path"] = "../auth.json"
        journal.write_bytes(b"".join(v2._canonical_json_bytes(row) for row in records))
    else:
        chunk = next((runtime / "concurrent_runtime_batch_spool").rglob("*.json"))
        chunk.write_bytes(chunk.read_bytes() + b" ")
    before = _inventory(tmp_path)
    output = tmp_path / "new-campaign"
    assert cli.main(["prepare-recovery", "--plan", str(plan), "--output-dir", str(output)]) != 0
    assert not output.exists() and _inventory(tmp_path) == before
