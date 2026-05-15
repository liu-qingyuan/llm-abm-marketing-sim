from __future__ import annotations

import argparse

import uvicorn

from .app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the local LLM-ABM Web console.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--artifact-root", default="runs/web")
    args = parser.parse_args(argv)
    url = f"http://{args.host}:{args.port}"
    print(f"LLM-ABM Web console: {url}")
    uvicorn.run(create_app(artifact_root=args.artifact_root), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
