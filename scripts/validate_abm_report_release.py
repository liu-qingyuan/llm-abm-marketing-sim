#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any


class ReleaseValidationError(ValueError):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseValidationError(f"cannot read valid JSON from {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_artifact(source_dir: Path, raw_path: object, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ReleaseValidationError(f"{label} must be a non-empty relative path")
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReleaseValidationError(f"{label} is not a safe relative path: {raw_path}")
    artifact = source_dir / relative
    if artifact.is_symlink() or not artifact.is_file():
        raise ReleaseValidationError(f"{label} is missing, not a file, or a symlink: {raw_path}")
    return artifact


def _reject_symlinks(source_dir: Path) -> None:
    if source_dir.is_symlink():
        raise ReleaseValidationError("source directory must not be a symlink")
    for directory, directory_names, file_names in os.walk(source_dir, followlinks=False):
        root = Path(directory)
        for name in [*directory_names, *file_names]:
            if (root / name).is_symlink():
                raise ReleaseValidationError(f"source directory contains symlink: {(root / name).relative_to(source_dir)}")


def _expect_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise ReleaseValidationError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def validate_release(*, repo_root: Path, contract_path: Path, source_dir: Path) -> dict[str, object]:
    repo_root = repo_root.resolve()
    contract = _load_json(contract_path)
    if not isinstance(contract, dict):
        raise ReleaseValidationError("release contract must be a JSON object")
    _expect_equal(contract.get("schema_version"), "abm-report-release-contract-v1", "contract schema_version")
    _expect_equal(
        contract.get("payload_schema_version"),
        "final-research-ranking-report-payload-v4",
        "v1 payload_schema_version",
    )
    _expect_equal(
        contract.get("manifest_version"),
        "final-research-ranking-runtime-v2",
        "v1 manifest_version",
    )
    _expect_equal(
        contract.get("sampling_method"),
        "seed_first_research_sample_v1",
        "v1 sampling_method",
    )
    _expect_equal(contract.get("sampling_status"), "validation_run", "v1 sampling_status")

    raw_expected_source = contract.get("source_directory")
    if not isinstance(raw_expected_source, str):
        raise ReleaseValidationError("contract source_directory must be a relative path")
    expected_relative = Path(raw_expected_source)
    if expected_relative.is_absolute() or ".." in expected_relative.parts:
        raise ReleaseValidationError("contract source_directory must be a safe relative path")
    expected_source = (repo_root / expected_relative).resolve()
    resolved_source = source_dir.resolve()
    _expect_equal(resolved_source, expected_source, "source directory")
    try:
        resolved_source.relative_to(repo_root)
    except ValueError as exc:
        raise ReleaseValidationError("source directory must stay inside repo root") from exc
    if not source_dir.is_dir():
        raise ReleaseValidationError(f"source directory does not exist: {source_dir}")
    _reject_symlinks(source_dir)

    manifest = _load_json(_safe_artifact(source_dir, "artifact_manifest.json", "artifact manifest"))
    payload = _load_json(
        _safe_artifact(source_dir, "final_research_report_payload.json", "ranking report payload")
    )
    sample_audit = _load_json(_safe_artifact(source_dir, "seed_first_sample_audit.json", "sample audit"))
    sample_manifest = _load_json(_safe_artifact(source_dir, "sample_manifest.json", "sample manifest"))
    if not all(isinstance(value, dict) for value in (manifest, payload, sample_audit)):
        raise ReleaseValidationError("manifest, payload, and sample audit must be JSON objects")
    if not isinstance(sample_manifest, list):
        raise ReleaseValidationError("sample manifest must be a JSON array")

    sampling_method = contract.get("sampling_method")
    sampling_status = contract.get("sampling_status")
    role_counts = contract.get("sample_role_counts")
    if not isinstance(role_counts, dict) or not all(
        isinstance(role, str) and isinstance(count, int) and count >= 0 for role, count in role_counts.items()
    ):
        raise ReleaseValidationError("contract sample_role_counts must map roles to non-negative integers")

    _expect_equal(manifest.get("manifest_version"), contract.get("manifest_version"), "manifest version")
    _expect_equal(payload.get("schema_version"), contract.get("payload_schema_version"), "payload schema_version")
    _expect_equal(manifest.get("sampling_method"), sampling_method, "manifest sampling_method")
    _expect_equal(manifest.get("sampling_status"), sampling_status, "manifest sampling_status")
    _expect_equal(manifest.get("live_api_triggered"), False, "manifest live_api_triggered")
    _expect_equal(manifest.get("sample_role_counts"), role_counts, "manifest sample role counts")
    _expect_equal(sample_audit.get("sampling_method"), sampling_method, "sample audit sampling_method")
    _expect_equal(sample_audit.get("sampling_status"), sampling_status, "sample audit sampling_status")
    _expect_equal(sample_audit.get("roles", {}).get("counts"), role_counts, "sample audit role counts")
    _expect_equal(payload.get("run", {}).get("sampling_method"), sampling_method, "payload sampling_method")
    _expect_equal(payload.get("run", {}).get("sampling_status"), sampling_status, "payload sampling_status")
    _expect_equal(payload.get("sample_role_counts"), role_counts, "payload sample role counts")

    actual_role_counts = dict(Counter(record.get("sample_role") for record in sample_manifest))
    _expect_equal(actual_role_counts, role_counts, "sample manifest role counts")
    sample_size = sum(role_counts.values())
    _expect_equal(len(sample_manifest), sample_size, "sample manifest size")
    _expect_equal(manifest.get("counts", {}).get("sample_users"), sample_size, "manifest sample_users")
    _expect_equal(payload.get("run", {}).get("sample_size"), sample_size, "payload sample_size")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ReleaseValidationError("manifest artifacts must be a non-empty object")
    manifest_paths: set[str] = set()
    for key, raw_path in artifacts.items():
        _safe_artifact(source_dir, raw_path, f"manifest artifact {key}")
        manifest_paths.add(str(raw_path))

    downloads = payload.get("downloads")
    if not isinstance(downloads, dict) or not downloads:
        raise ReleaseValidationError("payload downloads must be a non-empty object")
    for key, raw_path in downloads.items():
        _safe_artifact(source_dir, raw_path, f"payload download {key}")

    expected_hashes = contract.get("artifact_sha256")
    if not isinstance(expected_hashes, dict) or not expected_hashes:
        raise ReleaseValidationError("contract artifact_sha256 must be a non-empty object")
    for raw_path, expected_hash in expected_hashes.items():
        artifact = _safe_artifact(source_dir, raw_path, f"hashed artifact {raw_path}")
        if raw_path != "artifact_manifest.json" and raw_path not in manifest_paths:
            raise ReleaseValidationError(f"hashed artifact is absent from manifest: {raw_path}")
        _expect_equal(_sha256(artifact), expected_hash, f"SHA-256 for {raw_path}")

    return {
        "source_directory": raw_expected_source,
        "sampling_method": sampling_method,
        "sampling_status": sampling_status,
        "sample_role_counts": role_counts,
        "artifact_count": len(artifacts),
        "report_sha256": expected_hashes.get("report.html"),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an approved persisted ABM report release")
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        result = validate_release(repo_root=args.repo_root, contract_path=args.contract, source_dir=args.source_dir)
    except ReleaseValidationError as exc:
        print(f"release validation error: {exc}", file=sys.stderr)
        return 1
    print(
        "Release evidence validated: "
        f"{result['source_directory']} | {result['sampling_method']} | {result['sampling_status']} | "
        f"report SHA-256 {result['report_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
