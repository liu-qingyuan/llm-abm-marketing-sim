#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from llm_abm_sim.report_deployment import (
    DeploymentAuthorizationError,
    DeploymentAuthorizationRequired,
    DeploymentTarget,
    authorize_deployment_files,
    verify_fresh_rollback_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an operational ABM report deployment authorization",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser(
        "preflight",
        help="Close a v13/v14 deployment plan before any remote connection",
    )
    preflight.add_argument("--deployment-facts", type=Path, required=True)
    preflight.add_argument("--authorization", type=Path)
    preflight.add_argument("--canonical-endpoint", required=True)
    preflight.add_argument("--host", required=True)
    preflight.add_argument("--remote-root", required=True)
    preflight.add_argument("--port", type=int, required=True)
    preflight.add_argument("--container-name", required=True)
    preflight.add_argument("--image", required=True)
    preflight.add_argument("--plan-output", type=Path, required=True)

    readback = subparsers.add_parser(
        "verify-readback",
        help="Match the first remote readback to the authorized rollback identity",
    )
    readback.add_argument("--plan", type=Path, required=True)
    readback.add_argument("--readback", type=Path, required=True)
    return parser


def _canonical_json(value: dict[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "preflight":
            target = DeploymentTarget(
                canonical_endpoint=args.canonical_endpoint,
                host=args.host,
                remote_root=args.remote_root,
                port=args.port,
                container_name=args.container_name,
                image=args.image,
            )
            plan = authorize_deployment_files(
                deployment_facts_path=args.deployment_facts,
                target=target,
                authorization_path=args.authorization,
                plan_output=args.plan_output,
            )
            print(
                "Deployment authorization validated: "
                f"{plan['release_contract_schema']} | {plan['release_id']} | "
                f"authorization SHA-256 {plan['authorization_sha256']}"
            )
            return 0
        verified = verify_fresh_rollback_files(
            plan_path=args.plan,
            readback_path=args.readback,
        )
        print(
            "Fresh rollback identity validated: "
            f"{verified['release_id']} | report {verified['report_sha256']} | "
            f"manifest {verified['manifest_sha256']}"
        )
        return 0
    except DeploymentAuthorizationRequired as exc:
        print(
            "deployment authorization required: " + _canonical_json(exc.readiness),
            file=sys.stderr,
        )
        return 2
    except DeploymentAuthorizationError as exc:
        print(f"deployment authorization error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
