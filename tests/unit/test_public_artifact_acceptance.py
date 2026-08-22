from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "scripts" / "verify_abm_public_artifact_bodies.py"
MIB = 1024 * 1024


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_fake_curl(bin_dir: Path) -> None:
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/usr/bin/env python3
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

args = sys.argv[1:]
output = Path(args[args.index('-o') + 1])
url = next(value for value in reversed(args) if value.startswith('https://'))
relative = unquote(urlsplit(url).path).lstrip('/')
if relative == os.environ.get('FAKE_CURL_FAIL_PATH'):
    raise SystemExit(28)
source = Path(os.environ['FAKE_PUBLIC_ROOT']) / relative
output.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(source, output)
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)


def _fixture(tmp_path: Path, *, small_count: int = 10) -> tuple[Path, Path, Path, Path]:
    snapshot = tmp_path / "snapshot"
    public = tmp_path / "public"
    bin_dir = tmp_path / "bin"
    downloads = tmp_path / "downloads"
    for directory in (snapshot, public, bin_dir, downloads):
        directory.mkdir()

    hashes: dict[str, str] = {}
    for index in range(small_count):
        relative = f"trace/batch-{index:06d}.json"
        for root in (snapshot, public):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"batch": index}), encoding="utf-8")
        hashes[relative] = _sha256(snapshot / relative)

    large_relative = "full-pool-source/large.jsonl"
    large = snapshot / large_relative
    large.parent.mkdir(parents=True, exist_ok=True)
    with large.open("wb") as stream:
        stream.seek(64 * MIB)
        stream.write(b"x")
    hashes[large_relative] = "a" * 64

    facts = tmp_path / "deployment-facts.json"
    facts.write_text(
        json.dumps(
            {
                "schema_version": "abm-report-deployment-facts-v1",
                "canonical_endpoint": "https://abm.example.test/",
                "release_id": "responsive-v11",
                "report_kind": "final-research",
                "artifact_sha256": hashes,
                "public_acceptance_artifacts": sorted(hashes),
            }
        ),
        encoding="utf-8",
    )
    _write_fake_curl(bin_dir)
    return facts, snapshot, public, downloads


def test_public_body_verifier_processes_fixed_batches_and_manifest_binds_large_files(
    tmp_path: Path,
) -> None:
    facts, snapshot, public, downloads = _fixture(tmp_path)
    summary = tmp_path / "summary.json"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path / 'bin'}:{env['PATH']}",
            "FAKE_PUBLIC_ROOT": str(public),
        }
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / ".venv" / "bin" / "python"),
            str(VERIFIER),
            "--deployment-facts",
            str(facts),
            "--snapshot-dir",
            str(snapshot),
            "--download-dir",
            str(downloads),
            "--summary-output",
            str(summary),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(summary.read_text(encoding="utf-8"))
    assert result == {
        "artifact_count": 11,
        "body_policy": "default-64mib-v1",
        "batch_count": 2,
        "batch_size": 8,
        "full_body_bytes": sum((snapshot / f"trace/batch-{index:06d}.json").stat().st_size for index in range(10)),
        "full_body_count": 10,
        "manifest_bound_bytes": 64 * MIB + 1,
        "manifest_bound_count": 1,
        "schema_version": "abm-public-artifact-body-acceptance-v1",
    }
    assert "Public body batch 1/2: 8 artifacts" in completed.stdout
    assert "Public body batch 2/2: 2 artifacts" in completed.stdout
    assert not list(downloads.iterdir())


def test_full_pool_paged_policy_body_hashes_presentation_files_not_bulk_json(
    tmp_path: Path,
) -> None:
    facts, snapshot, public, downloads = _fixture(tmp_path)
    document = json.loads(facts.read_text(encoding="utf-8"))
    document["report_kind"] = "full-pool"
    artifacts = (
        ("bulk/page.json", 5 * MIB, b"}"),
        ("downloads/results.csv", 5 * MIB, b"\n"),
        ("report.html", 5 * MIB, b">"),
        ("artifact_manifest.json", 5 * MIB, b"}"),
        ("trace/message_1/batch-000000.json", 128, b"}"),
        ("full-pool-source/small-rows.jsonl", 128, b"\n"),
        ("metadata.json", 128, b"}"),
    )
    for relative, size_bytes, suffix in artifacts:
        for root in (snapshot, public):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as stream:
                stream.seek(size_bytes - 1)
                stream.write(suffix)
        document["artifact_sha256"][relative] = _sha256(snapshot / relative)
    document["public_acceptance_artifacts"] = sorted(document["artifact_sha256"])
    facts.write_text(json.dumps(document), encoding="utf-8")
    summary = tmp_path / "summary.json"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path / 'bin'}:{env['PATH']}",
            "FAKE_PUBLIC_ROOT": str(public),
        }
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / ".venv" / "bin" / "python"),
            str(VERIFIER),
            "--deployment-facts",
            str(facts),
            "--snapshot-dir",
            str(snapshot),
            "--download-dir",
            str(downloads),
            "--summary-output",
            str(summary),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(summary.read_text(encoding="utf-8"))
    assert result["body_policy"] == "full-pool-paged-v1"
    assert result["full_body_count"] == 4
    assert result["manifest_bound_count"] == 14
    assert "Public body policy: full-pool-paged-v1" in completed.stdout


def test_public_body_verifier_fails_closed_for_one_batch_member(tmp_path: Path) -> None:
    facts, snapshot, public, downloads = _fixture(tmp_path)
    summary = tmp_path / "summary.json"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path / 'bin'}:{env['PATH']}",
            "FAKE_PUBLIC_ROOT": str(public),
            "FAKE_CURL_FAIL_PATH": "trace/batch-000003.json",
        }
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / ".venv" / "bin" / "python"),
            str(VERIFIER),
            "--deployment-facts",
            str(facts),
            "--snapshot-dir",
            str(snapshot),
            "--download-dir",
            str(downloads),
            "--summary-output",
            str(summary),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 1
    assert "public artifact download failed: trace/batch-000003.json" in completed.stderr
    assert not summary.exists()
    assert not list(downloads.iterdir())
