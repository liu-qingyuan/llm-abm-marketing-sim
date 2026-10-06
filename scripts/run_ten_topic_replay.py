#!/usr/bin/env python3
"""Explicit zero-Provider ten-topic full-pool replay; never publishes a website."""

import argparse
import json
from pathlib import Path

from llm_abm_sim.ten_topic_replay import run_ten_topic_replay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["judgment-source", "realized-source", "final-dataset", "output-dir"]:
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = run_ten_topic_replay(**vars(args))
    print(
        json.dumps(
            {k: result[k] for k in ["source_identity", "counts", "action_counts", "verification", "provider_calls"]},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
