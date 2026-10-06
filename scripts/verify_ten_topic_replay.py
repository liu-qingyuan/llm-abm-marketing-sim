#!/usr/bin/env python3
"""Reopen and independently verify an explicitly selected ten-topic replay."""

import argparse
import json
from pathlib import Path

from llm_abm_sim.ten_topic_replay import verify_ten_topic_replay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    result = verify_ten_topic_replay(parser.parse_args().source_dir)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
