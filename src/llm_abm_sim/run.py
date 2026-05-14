from __future__ import annotations

import argparse
from pathlib import Path

from .runner import ExperimentRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an LLM-ABM marketing diffusion simulation.")
    parser.add_argument("--config", required=True, help="Path to YAML/JSON simulation config.")
    parser.add_argument("--output", required=True, help="Directory where run artifacts are written.")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    output_path = ExperimentRunner.from_config_file(config_path).run_and_write(args.output, config_path=config_path)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
