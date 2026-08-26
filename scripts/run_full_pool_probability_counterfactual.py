#!/usr/bin/env python3
"""Run a zero-Provider fixed-schedule Full-Pool probability counterfactual."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from llm_abm_sim.full_pool_probability_counterfactual import (
    ProbabilityCounterfactualRequest,
    run_probability_counterfactual,
)

_CONFIRMATION = "FULL_POOL_PROBABILITY_COUNTERFACTUAL_ZERO_PROVIDER"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--confirm-zero-provider-counterfactual",
        required=True,
        metavar="TOKEN",
        help=f"Exact opt-in token: {_CONFIRMATION}",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.confirm_zero_provider_counterfactual != _CONFIRMATION:
        raise ValueError("zero-Provider counterfactual confirmation token is invalid")
    result = run_probability_counterfactual(
        ProbabilityCounterfactualRequest(
            source_root=arguments.source_root,
            source_manifest_sha256=arguments.source_manifest_sha256,
            output_dir=arguments.output_dir,
            seed=arguments.seed,
        )
    )
    payload = asdict(result)
    payload["output_dir"] = str(result.output_dir)
    payload["provider_calls"] = 0
    payload["live_api_triggered"] = False
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
