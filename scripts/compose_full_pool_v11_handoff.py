#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from llm_abm_sim.concurrent_robustness_release import (
    compose_strict_full_pool_v11_execution_handoff,
)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compose a zero-call Release v11 operational handoff")
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--fresh-execution-manifest", required=True, type=Path)
    parser.add_argument("--implementation-commit", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    handoff = compose_strict_full_pool_v11_execution_handoff(
        repo_root=args.repo_root,
        fresh_execution_manifest_path=args.fresh_execution_manifest,
        implementation_commit=args.implementation_commit,
        release_id=args.release_id,
    )
    payload = _json_bytes(handoff)
    output = Path(os.path.abspath(args.output.expanduser()))
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    print(
        json.dumps(
            {
                "output": str(output),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "provider_calls_during_composition": 0,
                "operational_authorization_required": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
