from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_abm_sim.retention import (
    CacheEvidence,
    DuplicateEvidence,
    RetentionAuditor,
    RetentionAuditResult,
    RetentionEntry,
    RetentionEvidenceReference,
    RetentionManifest,
    load_retention_manifest,
    render_retention_report,
)


def _write(root: Path, relative: str, content: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _entry(
    root: str,
    classification: str,
    action: str,
    *,
    evidence: RetentionEvidenceReference | None = None,
    duplicate: DuplicateEvidence | None = None,
    cache: CacheEvidence | None = None,
) -> RetentionEntry:
    return RetentionEntry(
        root=root,
        root_type="directory",
        ownership="test",
        classification=classification,
        basis="test evidence",
        planned_action=action,
        evidence_reference=evidence,
        duplicate_evidence=duplicate,
        cache_evidence=cache,
    )


def _manifest(*entries: RetentionEntry) -> RetentionManifest:
    return RetentionManifest(schema_version="retention-manifest-v1", entries=list(entries))


def test_audit_covers_four_classifications_and_is_deterministic(tmp_path: Path) -> None:
    _write(tmp_path, "contract/evidence.json", b'{"source_directory":"contract"}')
    _write(tmp_path, "contract/release.txt", b"protected")
    _write(tmp_path, "lineage/archive.txt", b"lineage")
    _write(tmp_path, "cache/pytest.bin", b"cache")
    _write(tmp_path, "duplicate/a.txt", b"same")
    _write(tmp_path, "retained/a.txt", b"same")
    _write(tmp_path, "unknown/candidate.txt", b"unknown")

    duplicate = DuplicateEvidence(
        candidate_root="duplicate",
        retained_root="retained",
        relative_files=["a.txt"],
        sha256_map={"a.txt": _sha256(b"same")},
        expected_bytes=4,
        approved_action="delete",
    )
    manifest = _manifest(
        _entry(
            "contract",
            "contract-protected",
            "retain",
            evidence=RetentionEvidenceReference(
                path="contract/evidence.json",
                identity_field="source_directory",
                expected_identity="contract",
            ),
        ),
        _entry("lineage", "lineage-only", "human-review"),
        _entry(
            "cache",
            "reproducible-ephemeral",
            "delete",
            cache=CacheEvidence(
                exact_root="cache",
                producer="pytest",
                rebuild_validation="pytest -q",
            ),
        ),
        _entry("duplicate", "reproducible-ephemeral", "delete", duplicate=duplicate),
        _entry("unknown", "unknown", "defer"),
    )

    first = RetentionAuditor(tmp_path).audit(manifest)
    second = RetentionAuditor(tmp_path).audit(manifest)

    assert isinstance(first, RetentionAuditResult)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.ready_for_cleanup is False
    assert first.protected_roots == ["contract"]
    assert first.approved_candidates == ["cache", "duplicate"]
    assert first.human_review_roots == ["lineage", "unknown"]
    assert first.deferred_unknowns == ["unknown"]
    assert first.aggregate_bytes == 9
    assert {action.path for action in first.approved_actions} == {"cache/pytest.bin", "duplicate/a.txt"}
    assert first.approved_directories[0].path == "cache"
    assert "candidate.txt" not in render_retention_report(first)
    assert render_retention_report(first) == render_retention_report(second)


def test_manifest_rejects_unrecognized_classification() -> None:
    with pytest.raises(ValidationError):
        RetentionEntry(
            root="root",
            root_type="directory",
            ownership="test",
            classification="protected",  # type: ignore[arg-type]
            basis="test",
            planned_action="retain",
        )


def test_path_escape_and_absolute_paths_are_deferred_without_allowlist(tmp_path: Path) -> None:
    manifest = _manifest(
        _entry("../outside", "unknown", "defer"),
        _entry(str(tmp_path / "absolute"), "unknown", "defer"),
    )

    result = RetentionAuditor(tmp_path).audit(manifest)

    assert result.approved_actions == []
    assert {violation.code for violation in result.violations} == {"path-escape", "absolute-path"}
    assert result.ready_for_cleanup is False


def test_symlink_component_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    _write(tmp_path, "target/file.txt", b"payload")
    (tmp_path / "link").symlink_to(target, target_is_directory=True)

    result = RetentionAuditor(tmp_path).audit(_manifest(_entry("link", "unknown", "defer")))

    assert any(violation.code == "symlink-component" for violation in result.violations)
    assert result.approved_actions == []


def test_duplicate_missing_extra_and_hash_mismatch_fail_closed(tmp_path: Path) -> None:
    _write(tmp_path, "candidate/a.txt", b"candidate")
    _write(tmp_path, "candidate/extra.txt", b"extra")
    _write(tmp_path, "retained/a.txt", b"retained")
    duplicate = DuplicateEvidence(
        candidate_root="candidate",
        retained_root="retained",
        relative_files=["a.txt"],
        sha256_map={"a.txt": _sha256(b"candidate")},
        expected_bytes=9,
        approved_action="delete",
    )

    result = RetentionAuditor(tmp_path).audit(
        _manifest(_entry("candidate", "reproducible-ephemeral", "delete", duplicate=duplicate))
    )

    assert result.approved_actions == []
    assert any(violation.code == "duplicate-mismatch" for violation in result.violations)
    assert result.ready_for_cleanup is False


def test_cache_requires_exact_root_and_rebuild_evidence(tmp_path: Path) -> None:
    _write(tmp_path, "cache/a.txt", b"cache")

    without_evidence = RetentionAuditor(tmp_path).audit(_manifest(_entry("cache", "reproducible-ephemeral", "delete")))
    assert without_evidence.approved_actions == []
    assert any(violation.code == "missing-rebuild-evidence" for violation in without_evidence.violations)

    wrong_root = RetentionAuditor(tmp_path).audit(
        _manifest(
            _entry(
                "cache",
                "reproducible-ephemeral",
                "delete",
                cache=CacheEvidence(
                    exact_root="other-cache",
                    producer="pytest",
                    rebuild_validation="pytest -q",
                ),
            )
        )
    )
    assert wrong_root.approved_actions == []
    assert any(violation.code == "cache-root-mismatch" for violation in wrong_root.violations)


def test_evidence_identity_mismatch_and_classification_conflict_are_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "evidence.json", b'{"source_directory":"other"}')
    _write(tmp_path, "root/file.txt", b"root")
    entries = [
        _entry(
            "root",
            "contract-protected",
            "retain",
            evidence=RetentionEvidenceReference(
                path="evidence.json",
                identity_field="source_directory",
                expected_identity="root",
            ),
        ),
        _entry("root", "unknown", "defer"),
    ]

    result = RetentionAuditor(tmp_path).audit(_manifest(*entries))

    assert result.approved_actions == []
    assert any(violation.code == "classification-conflict" for violation in result.violations)
    assert any(violation.code == "evidence-mismatch" for violation in result.violations)


def test_directory_action_records_exact_files_and_empty_postcondition(tmp_path: Path) -> None:
    _write(tmp_path, "cache/nested/item.txt", b"item")
    manifest = _manifest(
        _entry(
            "cache",
            "reproducible-ephemeral",
            "delete",
            cache=CacheEvidence(
                exact_root="cache",
                producer="test producer",
                rebuild_validation="test rebuild",
            ),
        )
    )

    result = RetentionAuditor(tmp_path).audit(manifest)

    assert [action.path for action in result.approved_actions] == ["cache/nested/item.txt"]
    assert len(result.approved_directories) == 2
    root_action = next(directory for directory in result.approved_directories if directory.path == "cache")
    assert root_action.verified_empty_after_file_actions is True
    assert root_action.files_processed == ["cache/nested/item.txt"]
    assert root_action.directories_processed == ["cache/nested"]


def test_load_manifest_round_trip_and_no_filesystem_mutation(tmp_path: Path) -> None:
    _write(tmp_path, "root/file.txt", b"unchanged")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            _manifest(_entry("root", "unknown", "defer")).model_dump(mode="json"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    before = (tmp_path / "root/file.txt").read_bytes()

    loaded = load_retention_manifest(manifest_path)
    result = RetentionAuditor(tmp_path).audit(loaded)

    assert loaded == _manifest(_entry("root", "unknown", "defer"))
    assert (tmp_path / "root/file.txt").read_bytes() == before
    assert result.approved_actions == []


def test_non_regular_file_is_rejected_for_cache(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO is not available")
    cache = tmp_path / "cache"
    cache.mkdir()
    os.mkfifo(cache / "pipe")
    result = RetentionAuditor(tmp_path).audit(
        _manifest(
            _entry(
                "cache",
                "reproducible-ephemeral",
                "delete",
                cache=CacheEvidence(
                    exact_root="cache",
                    producer="test producer",
                    rebuild_validation="test rebuild",
                ),
            )
        )
    )

    assert result.approved_actions == []
    assert any(violation.code == "unexpected-file-type" for violation in result.violations)


def test_missing_root_is_not_a_cleanup_allowlist(tmp_path: Path) -> None:
    result = RetentionAuditor(tmp_path).audit(
        _manifest(
            _entry(
                "missing-cache",
                "reproducible-ephemeral",
                "delete",
                cache=CacheEvidence(
                    exact_root="missing-cache",
                    producer="test producer",
                    rebuild_validation="test rebuild",
                ),
            )
        )
    )

    assert result.approved_actions == []
    assert any(violation.code == "missing-root" for violation in result.violations)


def test_protected_root_requires_evidence_and_secret_paths_are_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "protected/file.txt", b"protected")
    _write(tmp_path, "config/.env", b"must not be inspected")
    result = RetentionAuditor(tmp_path).audit(
        _manifest(
            _entry("protected", "contract-protected", "retain"),
            _entry(
                "config/.env",
                "unknown",
                "defer",
                evidence=RetentionEvidenceReference(path="config/.env"),
            ),
        )
    )

    assert result.approved_actions == []
    assert any(violation.code == "missing-evidence" for violation in result.violations)
    assert any(violation.code == "forbidden-secret-path" for violation in result.violations)


def test_duplicate_candidate_cannot_equal_retained_root(tmp_path: Path) -> None:
    _write(tmp_path, "candidate/file.txt", b"same")
    duplicate = DuplicateEvidence(
        candidate_root="candidate",
        retained_root="candidate",
        relative_files=["file.txt"],
        sha256_map={"file.txt": _sha256(b"same")},
        expected_bytes=4,
        approved_action="delete",
    )

    result = RetentionAuditor(tmp_path).audit(
        _manifest(_entry("candidate", "reproducible-ephemeral", "delete", duplicate=duplicate))
    )

    assert result.approved_actions == []
    assert any(violation.code == "duplicate-root-mismatch" for violation in result.violations)


def test_raw_cache_root_and_retained_raw_root_are_not_hashed(tmp_path: Path) -> None:
    _write(tmp_path, "data/raw/cache/payload.json", b"raw payload")
    _write(tmp_path, "candidate/file.txt", b"safe")
    duplicate = DuplicateEvidence(
        candidate_root="candidate",
        retained_root="data/raw/cache",
        relative_files=["file.txt"],
        sha256_map={"file.txt": _sha256(b"safe")},
        expected_bytes=4,
        approved_action="delete",
    )

    cache_result = RetentionAuditor(tmp_path).audit(
        _manifest(
            _entry(
                "data/raw/cache",
                "reproducible-ephemeral",
                "delete",
                cache=CacheEvidence(
                    exact_root="data/raw/cache",
                    producer="test producer",
                    rebuild_validation="test rebuild",
                ),
            )
        )
    )
    duplicate_result = RetentionAuditor(tmp_path).audit(
        _manifest(_entry("candidate", "reproducible-ephemeral", "delete", duplicate=duplicate))
    )

    assert cache_result.approved_actions == []
    assert any(violation.code == "forbidden-payload-path" for violation in cache_result.violations)
    assert duplicate_result.approved_actions == []
    assert any(violation.code == "forbidden-payload-path" for violation in duplicate_result.violations)


def test_lineage_human_review_always_blocks_cleanup_ready(tmp_path: Path) -> None:
    _write(tmp_path, "lineage/file.txt", b"lineage")
    manifest = _manifest(
        _entry(
            "lineage",
            "lineage-only",
            "human-review",
            evidence=RetentionEvidenceReference(path="lineage/file.txt"),
        )
    )

    result = RetentionAuditor(tmp_path).audit(manifest)

    assert result.violations == []
    assert result.human_review_roots == ["lineage"]
    assert result.ready_for_cleanup is False


def test_retained_duplicate_env_path_is_rejected_before_hash(tmp_path: Path) -> None:
    _write(tmp_path, "candidate/file.txt", b"safe")
    duplicate = DuplicateEvidence(
        candidate_root="candidate",
        retained_root="safe/.env",
        relative_files=["file.txt"],
        sha256_map={"file.txt": _sha256(b"safe")},
        expected_bytes=4,
        approved_action="delete",
    )

    result = RetentionAuditor(tmp_path).audit(
        _manifest(_entry("candidate", "reproducible-ephemeral", "delete", duplicate=duplicate))
    )

    assert result.approved_actions == []
    assert any(violation.code == "forbidden-secret-path" for violation in result.violations)
