from __future__ import annotations

import argparse
from pathlib import Path

from llm_abm_sim.retention import RetentionAuditResult, audit_retention, render_retention_report


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_manifest() -> str:
    return "configs/retention/manifest.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a read-only repository retention audit")
    parser.add_argument("--repo-root", type=Path, default=None, help="repository root (default: project root)")
    parser.add_argument("--manifest", type=str, default=None, help="tracked repo-relative retention manifest path")
    parser.add_argument("--report", type=Path, default=None, help="optional Markdown output path")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser


def _render(result: RetentionAuditResult, output_format: str) -> str:
    if output_format == "json":
        return result.model_dump_json(indent=2) + "\n"
    return render_retention_report(result)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root or _default_repo_root()
    manifest_path = args.manifest or _default_manifest()
    result = audit_retention(manifest_path, repo_root=repo_root)
    rendered = _render(result, args.format)
    if args.report is None:
        print(rendered, end="")
    else:
        args.report.write_text(rendered, encoding="utf-8")
    return 0 if result.audit_valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
