#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_abm_sim.concurrent_robustness_release import promote_concurrent_robustness_release


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote a closed Concurrent Robustness Formal candidate")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--formal-root", type=Path, required=True)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--execution-contract", type=Path, required=True)
    parser.add_argument("--destination-dir", type=Path, required=True)
    parser.add_argument("--release-contract", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = promote_concurrent_robustness_release(
        repo_root=args.repo_root,
        formal_root=args.formal_root,
        study_root=args.study_root,
        workspace_root=args.workspace_root,
        candidate_dir=args.candidate_dir,
        execution_contract_path=args.execution_contract,
        destination_dir=args.destination_dir,
        release_contract_path=args.release_contract,
        release_id=args.release_id,
    )
    print(
        json.dumps(
            {
                "release_id": result.release_id,
                "source_dir": str(result.source_dir),
                "contract_path": str(result.contract_path),
                "report_sha256": result.report_sha256,
                "manifest_sha256": result.manifest_sha256,
                "release_identity_sha256": result.release_identity_sha256,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
