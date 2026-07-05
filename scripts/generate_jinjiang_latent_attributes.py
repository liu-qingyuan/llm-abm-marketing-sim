from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from llm_abm_sim.data_sources.latent_processed_variant import (
    LatentProcessedVariantRequest,
    generate_latent_processed_variant,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a Jinjiang latent-v1 processed dataset variant")
    parser.add_argument("--source-processed-dir", "--source-run", dest="source_processed_dir", required=True)
    parser.add_argument("--spec", dest="spec_path", required=True)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--output-processed-dir")
    output.add_argument("--output-run-id")
    parser.add_argument("--seed", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    source_processed_dir = Path(args.source_processed_dir)
    if args.output_processed_dir:
        output_processed_dir = Path(args.output_processed_dir)
        run_id = output_processed_dir.name
    else:
        run_id = str(args.output_run_id)
        output_processed_dir = source_processed_dir.parent / run_id

    result = generate_latent_processed_variant(
        LatentProcessedVariantRequest(
            source_processed_dir=source_processed_dir,
            output_processed_dir=output_processed_dir,
            spec_path=Path(args.spec_path),
            seed=args.seed,
            run_id=run_id,
        )
    )
    print(
        json.dumps(
            {
                "output_processed_dir": str(result.output_processed_dir),
                "user_count": result.user_count,
                "audit_path": str(result.audit_path),
                "markdown_audit_path": str(result.markdown_audit_path),
                "spec_snapshot_path": str(result.spec_snapshot_path),
                "written_files": [str(path) for path in result.written_files],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
