from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim.retention import RetentionAuditResult, audit_retention, render_retention_report

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "audit_retention.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Retention Test")
    return tmp_path


def _write(repo: Path, relative: str, content: bytes = b"fixture") -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _entry(
    root: str,
    classification: str,
    *,
    root_type: str = "directory",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "root": root,
        "root_type": root_type,
        "ownership": "test ownership",
        "classification": classification,
        "basis": "test policy evidence",
    }
    if evidence is not None:
        entry["evidence_reference"] = evidence
    return entry


def _manifest(*entries: dict[str, Any], schema: str = "retention-manifest-v2") -> dict[str, Any]:
    return {"schema_version": schema, "entries": list(entries)}


def _write_manifest(
    repo: Path, payload: dict[str, Any], *, tracked: bool = True, relative: str = "manifest.json"
) -> Path:
    path = _write(repo, relative, json.dumps(payload, ensure_ascii=False, indent=2).encode() + b"\n")
    if tracked:
        _git(repo, "add", relative)
    return path


def _run_cli(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, str(CLI), "--repo-root", str(repo), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _json_output(process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert process.stdout, process.stderr
    return json.loads(process.stdout)


def test_v2_audit_is_metadata_only_valid_with_unresolved_roots_and_deterministic(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    _write(repo, "protected/evidence.json", b'{"source_directory":"protected"}')
    _write(repo, "protected/release.bin", b"protected bytes")
    _write(repo, "protected/raw_prompt/unreadable-sentinel.txt", b"must never be opened")
    _write(repo, "lineage/archive.txt", b"lineage")
    _write(repo, "lineage-reference.md", b"human lineage reference")
    _write(repo, "ephemeral/cache.bin", b"cache")
    _write(repo, "ephemeral-reference.md", b"human rebuild reference")
    _write(repo, "unknown/candidate.txt", b"unknown")
    manifest_path = _write_manifest(
        repo,
        _manifest(
            _entry(
                "protected",
                "contract-protected",
                evidence={
                    "path": "protected/evidence.json",
                    "identity_field": "source_directory",
                    "expected_identity": "protected",
                },
            ),
            _entry("lineage", "lineage-only", evidence={"path": "lineage-reference.md"}),
            _entry("ephemeral", "reproducible-ephemeral", evidence={"path": "ephemeral-reference.md"}),
            _entry("unknown", "unknown"),
        ),
    )

    original_read_bytes = Path.read_bytes

    def fail_on_sentinel(path: Path) -> bytes:
        if path.name == "unreadable-sentinel.txt":
            raise AssertionError("retention auditor opened a root file")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_on_sentinel)
    first = audit_retention("manifest.json", repo_root=repo)
    second = audit_retention("manifest.json", repo_root=repo)

    assert isinstance(first, RetentionAuditResult)
    assert first.audit_valid is True
    assert first.manifest_sha256 == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert first.protected_roots == ["protected"]
    assert first.lineage_roots == ["lineage"]
    assert first.ephemeral_roots == ["ephemeral"]
    assert first.unresolved_roots == ["unknown"]
    assert first.metadata.regular_file_count == 6
    assert first.metadata.directory_count == 5
    assert first.metadata.observed_bytes == sum(
        path.stat().st_size
        for path in [
            repo / "protected/evidence.json",
            repo / "protected/release.bin",
            repo / "protected/raw_prompt/unreadable-sentinel.txt",
            repo / "lineage/archive.txt",
            repo / "ephemeral/cache.bin",
            repo / "unknown/candidate.txt",
        ]
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert render_retention_report(first) == render_retention_report(second)
    serialized = first.model_dump(mode="json")
    assert "ready_for_cleanup" not in serialized
    assert "approved_actions" not in serialized
    assert "approved_directories" not in serialized
    assert "planned_action" not in serialized
    assert "sha256" not in json.dumps(serialized["entry_results"])
    assert "unreadable-sentinel.txt" not in render_retention_report(first)
    assert "This read-only audit never authorizes deletion" in render_retention_report(first)


def test_dirty_tracked_manifest_is_allowed_and_hash_binds_worktree_bytes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "root/file.txt", b"root")
    manifest_path = _write_manifest(repo, _manifest(_entry("root", "unknown")))
    manifest_path.write_text(
        json.dumps(_manifest(_entry("root", "unknown")), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = audit_retention("manifest.json", repo_root=repo)

    assert result.audit_valid is True
    assert result.manifest_sha256 == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert (
        "manifest.json"
        in subprocess.run(["git", "status", "--short"], cwd=repo, check=True, capture_output=True, text=True).stdout
    )


def test_cli_json_markdown_and_exit_status_keep_valid_unknown_roots_successful(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "root/file.txt", b"root")
    _write_manifest(repo, _manifest(_entry("root", "unknown")))

    json_result = _run_cli(repo, "--manifest", "manifest.json", "--format", "json")
    markdown_result = _run_cli(repo, "--manifest", "manifest.json", "--format", "markdown")

    assert json_result.returncode == 0, json_result.stderr
    assert markdown_result.returncode == 0, markdown_result.stderr
    payload = _json_output(json_result)
    assert payload["schema_version"] == "retention-audit-v2"
    assert payload["audit_valid"] is True
    assert payload["unresolved_roots"] == ["root"]
    assert "audit_valid: `true`" in markdown_result.stdout
    assert "manifest_sha256: `" in markdown_result.stdout
    assert "regular_file_count: `1`" in markdown_result.stdout
    assert "ready_for_cleanup" not in json_result.stdout + markdown_result.stdout


def test_cli_rejects_historical_v1_without_fallback(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest_path = _write_manifest(
        repo,
        _manifest(
            _entry("root", "unknown"),
            schema="retention-manifest-v1",
        ),
    )
    _write(repo, "root/file.txt", b"root")

    result = _run_cli(repo, "--manifest", "manifest.json", "--format", "json")
    payload = _json_output(result)

    assert result.returncode == 2
    assert payload["audit_valid"] is False
    assert payload["manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert payload["violations"][0]["code"] == "unsupported-schema"
    assert "retention-manifest-v1" in payload["violations"][0]["message"]
    assert "ready_for_cleanup" not in result.stdout


@pytest.mark.parametrize(
    ("manifest_path", "expected_code"),
    [
        ("../manifest.json", "path-escape"),
        ("/tmp/manifest.json", "absolute-path"),
        ("configs//manifest.json", "invalid-path"),
        ("configs/./manifest.json", "invalid-path"),
    ],
)
def test_manifest_path_must_be_canonical_and_repo_relative(
    tmp_path: Path, manifest_path: str, expected_code: str
) -> None:
    repo = _repo(tmp_path)
    _write_manifest(repo, _manifest(_entry("root", "unknown")), relative="configs/manifest.json")
    _write(repo, "root/file.txt", b"root")

    result = _run_cli(repo, "--manifest", manifest_path, "--format", "json")
    payload = _json_output(result)

    assert result.returncode == 2
    assert payload["violations"][0]["code"] == expected_code
    assert payload["entry_results"] == []


def test_untracked_manifest_symlink_and_symlink_parent_fail_before_root_inventory(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "root/unreadable-sentinel.txt", b"must never be opened")
    untracked = _write_manifest(repo, _manifest(_entry("root", "unknown")), tracked=False)
    assert untracked.exists()
    untracked_result = _run_cli(repo, "--manifest", "manifest.json", "--format", "json")
    assert untracked_result.returncode == 2
    assert _json_output(untracked_result)["violations"][0]["code"] == "manifest-not-tracked"

    _git(repo, "add", "manifest.json")
    target = _write(repo, "tracked-manifest.json", json.dumps(_manifest(_entry("root", "unknown"))).encode())
    link = repo / "manifest-link.json"
    link.symlink_to(target)
    _git(repo, "add", "manifest-link.json")
    symlink_result = _run_cli(repo, "--manifest", "manifest-link.json", "--format", "json")
    assert symlink_result.returncode == 2
    assert _json_output(symlink_result)["violations"][0]["code"] == "symlink-component"

    alias = repo / "alias"
    alias.symlink_to(repo / "nested", target_is_directory=True)
    _write(repo, "nested/manifest.json", json.dumps(_manifest(_entry("root", "unknown"))).encode())
    _git(repo, "add", "nested/manifest.json")
    parent_result = _run_cli(repo, "--manifest", "alias/manifest.json", "--format", "json")
    assert parent_result.returncode == 2
    assert _json_output(parent_result)["violations"][0]["code"] == "symlink-component"


def test_root_canonical_identity_and_symlink_components_fail_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "root/file.txt", b"root")
    _write_manifest(
        repo,
        _manifest(
            _entry("root", "contract-protected", evidence={"path": "root/file.txt"}),
            _entry("root", "unknown"),
            _entry("root/.", "unknown"),
            _entry("root//file.txt", "unknown"),
        ),
    )

    result = audit_retention("manifest.json", repo_root=repo)

    assert result.audit_valid is False
    codes = {violation.code for violation in result.violations}
    assert "classification-conflict" in codes
    assert "invalid-path" in codes
    assert result.entry_results[0].regular_file_count == 0

    (repo / "linked").symlink_to(repo / "root", target_is_directory=True)
    _write_manifest(repo, _manifest(_entry("linked", "unknown")))
    symlink_result = audit_retention("manifest.json", repo_root=repo)
    assert symlink_result.audit_valid is False
    assert any(item.code == "symlink-component" for item in symlink_result.violations)


def test_evidence_contract_requires_valid_reference_and_exact_structured_identity(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "protected/file.txt", b"protected")
    _write(repo, "evidence.json", b'{"source_directory":"other"}')
    _write(repo, "reference.md", b"human reference")

    _write_manifest(
        repo,
        _manifest(
            _entry("protected", "contract-protected"),
            _entry(
                "protected",
                "lineage-only",
                evidence={
                    "path": "evidence.json",
                    "identity_field": "source_directory",
                    "expected_identity": "protected",
                },
            ),
            _entry(
                "protected",
                "reproducible-ephemeral",
                evidence={
                    "path": "reference.md",
                    "identity_field": "source_directory",
                    "expected_identity": "protected",
                },
            ),
        ),
    )

    result = audit_retention("manifest.json", repo_root=repo)

    assert result.audit_valid is False
    assert {item.code for item in result.violations} >= {
        "missing-evidence",
        "evidence-mismatch",
        "classification-conflict",
    }


def test_root_type_violation_is_nonzero_but_unknown_and_lineage_do_not_imply_cleanup(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "file.txt", b"file")
    _write(repo, "reference.md", b"reference")
    _write_manifest(
        repo,
        _manifest(
            _entry("file.txt", "contract-protected", root_type="directory", evidence={"path": "reference.md"}),
            _entry("lineage", "lineage-only", evidence={"path": "reference.md"}),
            _entry("unknown", "unknown"),
        ),
    )

    result = audit_retention("manifest.json", repo_root=repo)

    assert result.audit_valid is False
    assert any(item.code == "unexpected-file-type" for item in result.violations)
    assert result.unresolved_roots == ["unknown"]
    assert not hasattr(result, "ready_for_cleanup")


def test_retention_module_and_package_root_expose_only_supported_surface() -> None:
    import llm_abm_sim
    import llm_abm_sim.retention as retention

    assert retention.__all__ == ["RetentionAuditResult", "audit_retention", "render_retention_report"]
    assert not hasattr(llm_abm_sim, "RetentionAuditResult")
    assert not hasattr(llm_abm_sim, "RetentionManifest")
    assert not hasattr(retention, "RetentionAuditor")
    assert not hasattr(retention, "DuplicateEvidence")
    assert not hasattr(retention, "CacheEvidence")
    assert not hasattr(retention, "load_retention_manifest")


def test_current_tracked_manifest_keeps_required_classification_shape() -> None:
    payload = json.loads((REPO_ROOT / "configs/retention/manifest.json").read_text(encoding="utf-8"))
    entries = payload["entries"]
    counts = {
        classification: sum(entry["classification"] == classification for entry in entries)
        for classification in {
            "contract-protected",
            "lineage-only",
            "reproducible-ephemeral",
            "unknown",
        }
    }

    assert payload["schema_version"] == "retention-manifest-v2"
    assert counts == {
        "contract-protected": 6,
        "lineage-only": 2,
        "reproducible-ephemeral": 1,
        "unknown": 3,
    }
    assert all("planned_action" not in entry for entry in entries)
    assert all("duplicate_evidence" not in entry and "cache_evidence" not in entry for entry in entries)
