#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_abm_sim.concurrent_robustness_evidence import close_presentation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Close a zero-provider Concurrent Robustness presentation")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--formal-root", type=Path, required=True)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--execution-contract", type=Path, required=True)
    parser.add_argument("--destination", "--destination-path", dest="destination", type=Path, required=True)
    parser.add_argument("--implementation-commit", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = close_presentation(
        repo_root=args.repo_root,
        formal_root=args.formal_root,
        study_root=args.study_root,
        workspace_root=args.workspace_root,
        candidate_dir=args.candidate_dir,
        execution_contract_path=args.execution_contract,
        destination_path=args.destination,
        implementation_commit=args.implementation_commit,
    )
    print(
        json.dumps(
            {
                "closure_path": str(result.closure_path),
                "closure_sha256": result.closure_sha256,
                "implementation_commit": result.implementation_commit,
                "new_candidate_identity_sha256": result.new_candidate_identity_sha256,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
