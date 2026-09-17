from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "audit_gpt_p0_judgment_reuse.py"


@pytest.mark.parametrize("kind", ["tampered", "missing", "symlink"])
def test_audit_cli_rejects_invalid_evidence_without_output(tmp_path: Path, kind: str) -> None:
    evidence = tmp_path / "Evidence.json"
    if kind == "tampered":
        evidence.write_text("{}")
    elif kind == "symlink":
        original = tmp_path / "original.json"
        original.write_text("{}")
        evidence.symlink_to(original)
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    output = tmp_path / "output"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--evidence", str(evidence), "--plan", str(plan),
         "--output-dir", str(output), "--audit-date", "2026-09-17"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    expected = "SHA-256 mismatch" if kind == "tampered" else "regular non-symlink file"
    assert expected in result.stderr
    assert not output.exists()
    assert plan.read_text() == "{}"
    if evidence.exists():
        assert evidence.read_text() == "{}"
