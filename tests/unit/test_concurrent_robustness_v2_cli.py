from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal_module
from llm_abm_sim import concurrent_robustness_operator as operator_module
from scripts import run_concurrent_robustness_v2 as cli
from tests.unit.test_concurrent_robustness_formal_execution import _NOW, _authorization_artifact, _request_bundle
from tests.unit.test_concurrent_robustness_operator import _result


def _request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Path]:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    request, _ = _request_bundle(contracts)
    qualifications = tmp_path / "qualifications"
    qualifications.mkdir()
    references = []
    for reference in request.qualification_artifacts:
        target = qualifications / reference.path.name
        reference.path.rename(target)
        references.append(reference.model_copy(update={"path": target}))
    request = request.model_copy(update={"qualification_artifacts": tuple(references)})
    path = contracts / "request.json"
    path.write_bytes(cli._canonical_json_bytes(request.model_dump(mode="json")))
    monkeypatch.setattr(formal_module, "_utc_now", lambda: _NOW)

    def denied(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("offline CLI must not set up a Provider or read credentials")

    monkeypatch.setattr(operator_module, "_runtime_credential", denied)
    monkeypatch.setattr(operator_module, "_new_client", denied)
    return request, path


def test_preflight_writes_readonly_bundle_beside_inputs_without_live_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    request, path = _request(tmp_path, monkeypatch)
    output = path.parent / "readiness"
    assert cli.main(["preflight", "--request", str(path), "--output-dir", str(output)]) == 0
    assert {p.name for p in output.iterdir()} == {
        "formal-readiness.json", "formal-authorization-template.json",
        "operational-issue-handoff.md", "preflight-audit.json",
    }
    readiness = json.loads((output / "formal-readiness.json").read_text())
    audit = json.loads((output / "preflight-audit.json").read_text())
    assert readiness["provider_calls"] == audit["provider_calls"] == audit["credential_reads"] == 0
    assert audit["authorization"] is False
    assert all(not p.stat().st_mode & 0o222 for p in output.iterdir())
    assert json.loads(capsys.readouterr().out)["status"] == "ready_for_human"
    assert not request.output_root.exists()
    original = {p.name: p.read_bytes() for p in output.iterdir()}
    assert cli.main(["preflight", "--request", str(path), "--output-dir", str(output)]) != 0
    assert original == {p.name: p.read_bytes() for p in output.iterdir()}


def test_authorize_and_check_use_exact_explicit_artifact_not_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    request, path = _request(tmp_path, monkeypatch)
    readiness = formal_module.authorization_readiness(request)
    template = tmp_path / "template.json"
    template.write_bytes(cli._canonical_json_bytes(readiness["authorization_template"]))
    plan = tmp_path / "plan.json"
    assert cli.main([
        "authorize", "--request", str(path), "--authorization", str(template),
        "--authorization-sha256", hashlib.sha256(template.read_bytes()).hexdigest(), "--plan-output", str(plan),
    ]) != 0
    assert not plan.exists()
    capsys.readouterr()
    authorization, digest, _ = _authorization_artifact(tmp_path, request)
    assert cli.main([
        "authorize", "--request", str(path), "--authorization", str(authorization),
        "--authorization-sha256", digest, "--plan-output", str(plan),
    ]) == 0
    authorized = json.loads(capsys.readouterr().out)
    assert authorized["status"] == "authorized_for_formal_execution"
    assert cli.main(["check-plan", "--plan", str(plan)]) == 0
    assert json.loads(capsys.readouterr().out)["plan_identity_sha256"] == authorized["plan_identity_sha256"]
    assert not request.output_root.exists()


@pytest.mark.parametrize("target_kind", ["source", "qualification", "formal_output", "symlink"])
def test_preflight_cannot_write_in_evidence_or_through_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_kind: str,
) -> None:
    request, path = _request(tmp_path, monkeypatch)
    source = path.parent / "formal-source"
    if target_kind == "source":
        output = source / "readiness"
    elif target_kind == "qualification":
        output = request.qualification_artifacts[0].path.parent / "readiness"
    elif target_kind == "formal_output":
        output = request.output_root
    else:
        link = tmp_path / "alias"
        link.symlink_to(path.parent, target_is_directory=True)
        output = link / "readiness"
    assert cli.main(["preflight", "--request", str(path), "--output-dir", str(output)]) != 0
    assert not output.exists()


def test_preflight_partial_write_has_no_ready_audit_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _request_value, path = _request(tmp_path, monkeypatch)
    output = path.parent / "readiness"
    original_open = Path.open

    def open_path(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == output / "operational-issue-handoff.md":
            raise OSError("synthetic input sentinel")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_path)
    assert cli.main(["preflight", "--request", str(path), "--output-dir", str(output)]) != 0
    assert output.exists() and not (output / "preflight-audit.json").exists()


@pytest.mark.parametrize("status", ["resumable", "complete", "stopped", "reconciliation_required"])
def test_run_returns_status_without_setting_live_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], status: str,
) -> None:
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    monkeypatch.setattr(operator_module, "run_concurrent_robustness_formal", lambda path: _result(None, tmp_path, status))
    assert cli.main(["run", "--plan", str(tmp_path / "plan.json")]) == (0 if status in {"complete", "resumable"} else 1)
    assert json.loads(capsys.readouterr().out)["status"] == status
    assert "LLM_ABM_RUN_LIVE_LLM" not in cli.os.environ


@pytest.mark.parametrize("interrupt", [False, True])
def test_run_errors_hide_raw_input_and_never_claim_zero_calls(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], interrupt: bool,
) -> None:
    def fail(_path: Path) -> Any:
        if interrupt:
            raise KeyboardInterrupt
        raise RuntimeError("synthetic-secret-sentinel")

    monkeypatch.setattr(operator_module, "run_concurrent_robustness_formal", fail)
    assert cli.main(["run", "--plan", "synthetic-secret-sentinel"]) != 0
    captured = capsys.readouterr()
    assert captured.err == "" and "synthetic-secret-sentinel" not in captured.out
    assert "provider_calls" not in json.loads(captured.out)


def test_bad_cli_arguments_are_safe_bounded_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", "--unsupported", "synthetic-secret-sentinel"]) != 0
    captured = capsys.readouterr()
    assert captured.err == "" and "synthetic-secret-sentinel" not in captured.out
    assert json.loads(captured.out)["category"] == "invalid_input"
