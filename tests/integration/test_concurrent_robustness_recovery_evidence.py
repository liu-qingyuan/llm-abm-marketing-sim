from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_abm_sim.concurrent_robustness_recovery_evidence import (
    RecoveryEvidenceError,
    close_concurrent_robustness_recovery_evidence,
    read_concurrent_robustness_recovery_evidence,
)


def test_incomplete_evidence_child_is_never_repaired(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.json"
    bundle.write_bytes(json.dumps({"schema_version": "invalid"}, separators=(",", ":")).encode())
    output = tmp_path / "report" / "evidence"
    output.mkdir(parents=True)
    (output / "foreign.txt").write_text("owned elsewhere", encoding="utf-8")

    with pytest.raises(RecoveryEvidenceError):
        close_concurrent_robustness_recovery_evidence(bundle, output_dir=output)

    assert (output / "foreign.txt").read_text(encoding="utf-8") == "owned elsewhere"
    with pytest.raises(RecoveryEvidenceError):
        read_concurrent_robustness_recovery_evidence(output / "evidence.json")


def test_reader_rejects_missing_evidence_inventory(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RecoveryEvidenceError):
        read_concurrent_robustness_recovery_evidence(evidence)
