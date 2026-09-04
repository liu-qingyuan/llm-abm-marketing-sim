#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlencode, urlparse

_BODY_LIMIT_BYTES = 64 * 1024 * 1024
_FULL_POOL_BODY_LIMIT_BYTES = 4 * 1024 * 1024
_FULL_POOL_BODY_PATHS = frozenset(
    {
        "artifact_manifest.json",
        "report.html",
        "trace/full-pool-trace-index.json",
    }
)
_FULL_POOL_BODY_SUFFIXES = frozenset({".csv", ".md", ".mmd"})
_V14_RELEASE_CONTRACT_SCHEMA = "abm-report-release-contract-v14"
_FULL_POOL_MANIFEST_BOUND_NAMES = frozenset({"concurrent_message_decision_trace.json"})
_BATCH_SIZE = 8
_CURL_RETRY_SECONDS = 1_800
_ARTIFACT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PublicArtifactAcceptanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Artifact:
    index: int
    relative_path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class _Summary:
    schema_version: str
    body_policy: str
    artifact_count: int
    full_body_count: int
    full_body_bytes: int
    manifest_bound_count: int
    manifest_bound_bytes: int
    batch_size: int
    batch_count: int


def _load_facts(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise PublicArtifactAcceptanceError("deployment facts must be a regular non-symlink file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicArtifactAcceptanceError("deployment facts are unreadable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "abm-report-deployment-facts-v1":
        raise PublicArtifactAcceptanceError("deployment facts schema is unsupported")
    return value


def _canonical_endpoint(facts: dict[str, object]) -> str:
    value = facts.get("canonical_endpoint")
    if not isinstance(value, str):
        raise PublicArtifactAcceptanceError("canonical endpoint is invalid")
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.port is not None
        or parsed.path != "/"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise PublicArtifactAcceptanceError("canonical endpoint is invalid")
    return value


def _release_id(facts: dict[str, object]) -> str:
    value = facts.get("release_id")
    if not isinstance(value, str) or not _RELEASE_ID_PATTERN.fullmatch(value):
        raise PublicArtifactAcceptanceError("release id is invalid")
    return value


def _body_policy(facts: dict[str, object]) -> str:
    report_kind = facts.get("report_kind")
    if report_kind not in {
        "final-research",
        "concurrent-message",
        "concurrent-robustness",
        "full-pool",
    }:
        raise PublicArtifactAcceptanceError("deployment report kind is invalid")
    return "full-pool-paged-v1" if report_kind == "full-pool" else "default-64mib-v1"


def _requires_full_body(
    artifact: _Artifact,
    policy: str,
    *,
    v14_workbook: bool,
) -> bool:
    if policy != "full-pool-paged-v1":
        return artifact.size_bytes <= _BODY_LIMIT_BYTES
    relative = PurePosixPath(artifact.relative_path)
    if (
        artifact.relative_path in _FULL_POOL_BODY_PATHS
        or relative.suffix in _FULL_POOL_BODY_SUFFIXES
        or (v14_workbook and relative.suffix == ".xlsx")
    ):
        return True
    if (
        relative.parts[0] == "trace"
        or relative.suffix == ".jsonl"
        or relative.name in _FULL_POOL_MANIFEST_BOUND_NAMES
        or "/runtime/snapshots/" in f"/{artifact.relative_path}/"
    ):
        return False
    return artifact.size_bytes <= _FULL_POOL_BODY_LIMIT_BYTES


def _artifacts(facts: dict[str, object], snapshot_dir: Path) -> list[_Artifact]:
    raw_hashes = facts.get("artifact_sha256")
    raw_public = facts.get("public_acceptance_artifacts")
    if not isinstance(raw_hashes, dict) or not raw_hashes:
        raise PublicArtifactAcceptanceError("deployment artifact hashes are missing")
    if not isinstance(raw_public, list) or raw_public != sorted(raw_hashes):
        raise PublicArtifactAcceptanceError("public artifact inventory is incomplete or unordered")

    artifacts: list[_Artifact] = []
    for index, (raw_path, raw_digest) in enumerate(sorted(raw_hashes.items()), start=1):
        if not isinstance(raw_path, str) or not _ARTIFACT_PATTERN.fullmatch(raw_path):
            raise PublicArtifactAcceptanceError("public artifact path is invalid")
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or "." in relative.parts or ".." in relative.parts:
            raise PublicArtifactAcceptanceError("public artifact path escapes the snapshot")
        if not isinstance(raw_digest, str) or not _SHA256_PATTERN.fullmatch(raw_digest):
            raise PublicArtifactAcceptanceError(f"public artifact digest is invalid: {raw_path}")
        target = snapshot_dir.joinpath(*relative.parts)
        if target.is_symlink() or not target.is_file():
            raise PublicArtifactAcceptanceError(f"public artifact is missing or unsafe: {raw_path}")
        artifacts.append(
            _Artifact(
                index=index,
                relative_path=raw_path,
                sha256=raw_digest,
                size_bytes=target.stat().st_size,
            )
        )
    return artifacts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_body(
    artifact: _Artifact,
    *,
    endpoint: str,
    release_id: str,
    download_dir: Path,
) -> None:
    output = download_dir / f"artifact-{artifact.index:06d}.body"
    target = f"{endpoint}{quote(artifact.relative_path, safe='/')}?{urlencode({'release': release_id})}"
    try:
        completed = subprocess.run(
            [
                "curl",
                "--noproxy",
                "*",
                "--http1.1",
                "--retry",
                "4",
                "--retry-all-errors",
                "--retry-delay",
                "2",
                "--retry-max-time",
                str(_CURL_RETRY_SECONDS),
                "-fsSL",
                "--max-time",
                str(_CURL_RETRY_SECONDS),
                target,
                "-o",
                str(output),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode != 0:
            raise PublicArtifactAcceptanceError(f"public artifact download failed: {artifact.relative_path}")
        if output.is_symlink() or not output.is_file() or output.stat().st_size != artifact.size_bytes:
            raise PublicArtifactAcceptanceError(f"public artifact byte count mismatch: {artifact.relative_path}")
        if _sha256(output) != artifact.sha256:
            raise PublicArtifactAcceptanceError(f"public artifact checksum mismatch: {artifact.relative_path}")
    finally:
        output.unlink(missing_ok=True)


def _write_summary(path: Path, summary: _Summary) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PublicArtifactAcceptanceError("summary output must be a regular non-symlink file")
    path.write_text(
        json.dumps(asdict(summary), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def verify(
    *,
    deployment_facts: Path,
    snapshot_dir: Path,
    download_dir: Path,
    summary_output: Path,
) -> _Summary:
    if snapshot_dir.is_symlink() or not snapshot_dir.is_dir():
        raise PublicArtifactAcceptanceError("snapshot directory is missing or unsafe")
    if download_dir.is_symlink() or not download_dir.is_dir():
        raise PublicArtifactAcceptanceError("download directory is missing or unsafe")
    if any(download_dir.iterdir()):
        raise PublicArtifactAcceptanceError("download directory must start empty")

    facts = _load_facts(deployment_facts)
    endpoint = _canonical_endpoint(facts)
    release_id = _release_id(facts)
    policy = _body_policy(facts)
    artifacts = _artifacts(facts, snapshot_dir)
    v14_workbook = (
        facts.get("release_contract_schema_version")
        == _V14_RELEASE_CONTRACT_SCHEMA
    )
    full_body = [
        artifact
        for artifact in artifacts
        if _requires_full_body(
            artifact,
            policy,
            v14_workbook=v14_workbook,
        )
    ]
    manifest_bound = [
        artifact
        for artifact in artifacts
        if not _requires_full_body(
            artifact,
            policy,
            v14_workbook=v14_workbook,
        )
    ]
    batch_count = (len(full_body) + _BATCH_SIZE - 1) // _BATCH_SIZE
    print(f"Public body policy: {policy}", flush=True)

    for offset in range(0, len(full_body), _BATCH_SIZE):
        batch = full_body[offset : offset + _BATCH_SIZE]
        batch_number = offset // _BATCH_SIZE + 1
        print(
            f"Public body batch {batch_number}/{batch_count}: {len(batch)} artifacts",
            flush=True,
        )
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = [
                executor.submit(
                    _verify_body,
                    artifact,
                    endpoint=endpoint,
                    release_id=release_id,
                    download_dir=download_dir,
                )
                for artifact in batch
            ]
            errors: list[PublicArtifactAcceptanceError] = []
            for future in futures:
                try:
                    future.result()
                except PublicArtifactAcceptanceError as exc:
                    errors.append(exc)
            if errors:
                raise errors[0]
        print(f"Public body batch {batch_number}/{batch_count}: passed", flush=True)

    summary = _Summary(
        schema_version="abm-public-artifact-body-acceptance-v1",
        body_policy=policy,
        artifact_count=len(artifacts),
        full_body_count=len(full_body),
        full_body_bytes=sum(artifact.size_bytes for artifact in full_body),
        manifest_bound_count=len(manifest_bound),
        manifest_bound_bytes=sum(artifact.size_bytes for artifact in manifest_bound),
        batch_size=_BATCH_SIZE,
        batch_count=batch_count,
    )
    _write_summary(summary_output, summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify public artifact bodies in bounded batches")
    parser.add_argument("--deployment-facts", type=Path, required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        verify(
            deployment_facts=args.deployment_facts,
            snapshot_dir=args.snapshot_dir,
            download_dir=args.download_dir,
            summary_output=args.summary_output,
        )
    except PublicArtifactAcceptanceError as exc:
        print(f"public artifact acceptance error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
