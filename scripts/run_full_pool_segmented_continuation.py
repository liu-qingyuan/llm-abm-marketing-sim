#!/usr/bin/env python3
"""Explicit freeze-after-external-stop operator for Issue #205 segmented continuation.

This command never sends a signal. ``dry-run`` emits either the exact manual-stop
instruction or an audited already-stopped precondition plus a confirmation token;
``cutover`` accepts only an absent PID with a released workspace lock. ``run`` is
separately protected by two live environment gates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from llm_abm_sim.full_pool_segmented_operator import (
    CutoverPlanRequest,
    FullPoolSegmentedCutoverOperator,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="validate explicit v1/process/dataset facts and write a plan")
    prepare.add_argument("--plan", type=Path, required=True)
    for name in (
        "prefix-workspace",
        "frozen-prefix-workspace",
        "frozen-prefix-staging",
        "continuation-workspace",
        "dataset-dir",
        "pidfile",
        "expected-cwd",
        "preflight-artifact",
        "cutover-artifact",
        "reconciliation-artifact",
        "continuation-authorization-artifact",
        "qualification-artifact",
    ):
        prepare.add_argument(f"--{name}", type=Path, required=True)
    prepare.add_argument("--expected-pid", type=int, required=True)
    prepare.add_argument("--expected-command", required=True)
    prepare.add_argument(
        "--process-precondition",
        choices=("running_external_stop", "already_stopped"),
        default="running_external_stop",
    )
    prepare.add_argument("--expected-v1-output-identity", required=True)
    prepare.add_argument("--expected-v1-operational-root", required=True)
    prepare.add_argument("--expected-v1-source-root", required=True)
    prepare.add_argument("--expected-v1-candidate-root", required=True)
    prepare.add_argument("--expected-v1-recorded-runtime-workspace", required=True)
    prepare.add_argument("--expected-v1-recorded-output-target", required=True)
    prepare.add_argument("--expected-v1-dataset-dir", required=True)
    prepare.add_argument("--expected-v1-run-identity-hash", required=True)
    prepare.add_argument("--expected-execution-contract-sha256", required=True)
    prepare.add_argument("--implementation-commit", required=True)
    prepare.add_argument("--dataset-hash", action="append", required=True, metavar="RELATIVE_PATH=SHA256")
    prepare.add_argument("--continuation-id", required=True)
    prepare.add_argument("--authorization-reference", required=True)
    prepare.add_argument("--logical-cap", type=int, required=True)
    prepare.add_argument("--physical-cap", type=int, required=True)
    prepare.add_argument("--max-concurrency", type=int, required=True)
    prepare.add_argument("--migration-unknown-physical-charge", type=int, required=True)
    prepare.add_argument("--stability-interval-seconds", type=float, default=2.0)
    prepare.add_argument("--stop-wait-timeout-seconds", type=float, default=120.0)

    for name, help_text in (
        ("status", "read-only prefix/suffix/physical/unknown/source status"),
        ("dry-run", "write audited preflight and exact external-stop instruction"),
        ("run", "validate artifacts and run the live ten-lane source-v2 continuation"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--plan", type=Path, required=True)
    cutover = commands.add_parser("cutover", help="freeze only after the external stop and exact confirmation")
    cutover.add_argument("--plan", type=Path, required=True)
    cutover.add_argument("--confirm", required=True)
    return parser


def _dataset_hashes(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        relative, separator, digest = value.partition("=")
        if not separator or not relative or not digest or relative in result:
            raise ValueError("each --dataset-hash must be one unique RELATIVE_PATH=SHA256 pair")
        result[relative] = digest
    return result


def _prepare_request(arguments: argparse.Namespace) -> CutoverPlanRequest:
    return CutoverPlanRequest(
        prefix_workspace=arguments.prefix_workspace,
        frozen_prefix_workspace=arguments.frozen_prefix_workspace,
        frozen_prefix_staging=arguments.frozen_prefix_staging,
        continuation_workspace=arguments.continuation_workspace,
        dataset_dir=arguments.dataset_dir,
        pidfile=arguments.pidfile,
        expected_pid=arguments.expected_pid,
        expected_command=arguments.expected_command,
        expected_cwd=arguments.expected_cwd,
        process_precondition=arguments.process_precondition,
        expected_v1_output_identity=arguments.expected_v1_output_identity,
        expected_v1_operational_root=arguments.expected_v1_operational_root,
        expected_v1_source_root=arguments.expected_v1_source_root,
        expected_v1_candidate_root=arguments.expected_v1_candidate_root,
        expected_v1_recorded_runtime_workspace=arguments.expected_v1_recorded_runtime_workspace,
        expected_v1_recorded_output_target=arguments.expected_v1_recorded_output_target,
        expected_v1_dataset_dir=arguments.expected_v1_dataset_dir,
        expected_v1_run_identity_hash=arguments.expected_v1_run_identity_hash,
        expected_execution_contract_sha256=arguments.expected_execution_contract_sha256,
        implementation_commit=arguments.implementation_commit,
        dataset_hashes=_dataset_hashes(arguments.dataset_hash),
        continuation_id=arguments.continuation_id,
        authorization_reference=arguments.authorization_reference,
        preflight_artifact=arguments.preflight_artifact,
        cutover_artifact=arguments.cutover_artifact,
        reconciliation_artifact=arguments.reconciliation_artifact,
        continuation_authorization_artifact=arguments.continuation_authorization_artifact,
        qualification_artifact=arguments.qualification_artifact,
        logical_cap=arguments.logical_cap,
        physical_cap=arguments.physical_cap,
        max_concurrency=arguments.max_concurrency,
        migration_unknown_physical_charge=arguments.migration_unknown_physical_charge,
        stability_interval_seconds=arguments.stability_interval_seconds,
        stop_wait_timeout_seconds=arguments.stop_wait_timeout_seconds,
    )


def _safe_result(value: Any) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def main() -> int:
    arguments = _parser().parse_args()
    operator = FullPoolSegmentedCutoverOperator()
    if arguments.command == "prepare":
        result = operator.prepare(arguments.plan, _prepare_request(arguments))
    elif arguments.command == "dry-run":
        result = operator.dry_run(arguments.plan)
    elif arguments.command == "cutover":
        result = operator.cutover(arguments.plan, confirmation_token=arguments.confirm)
    elif arguments.command == "status":
        result = operator.status(arguments.plan)
    elif arguments.command == "run":
        result = operator.run(arguments.plan)
    else:  # pragma: no cover - argparse owns command selection.
        raise AssertionError("unreachable command")
    print(json.dumps(_safe_result(result), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
