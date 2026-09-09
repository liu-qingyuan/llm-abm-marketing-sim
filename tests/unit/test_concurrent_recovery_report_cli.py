"""Explicit offline report/evidence entry points; no production mock mode."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_concurrent_robustness_v2 as cli


@pytest.mark.parametrize("command,argument", [
    ("close-recovery-evidence", "--bundle"),
    ("inspect-recovery-evidence", "--evidence"),
    ("export-recovery-report", "--bundle"),
    ("inspect-recovery-report", "--report"),
])
def test_recovery_report_cli_rejects_invalid_origins_without_creating_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    command: str, argument: str,
) -> None:
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    output = tmp_path / "not-created"
    args = [command, argument, str(tmp_path / "missing.json")]
    if command in {"close-recovery-evidence", "export-recovery-report"}:
        args += ["--output-dir", str(output)]
    assert cli.main(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["category"] == "recovery_report_invalid"
    assert not output.exists()
    assert "missing.json" not in json.dumps(result)
