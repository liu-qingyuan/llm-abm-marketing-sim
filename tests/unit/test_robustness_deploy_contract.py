from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_v5_deploy_binds_cli_release_id_and_canonical_domain() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")

    assert 'contract.get("release_id") != release_id' in script
    assert 'parsed.hostname != domain' in script
    assert 'contract.get("canonical_endpoint")' in script
    assert 'abm-report-release-contract-v5' in script


def test_public_acceptance_hashes_every_contract_artifact() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")

    assert 'for artifact, digest in sorted(contract.get("artifact_sha256", {}).items())' in script
    assert 'public artifact checksum mismatch: ${artifact}' in script
    assert 'shasum -a 256 "${public_artifact}"' in script
