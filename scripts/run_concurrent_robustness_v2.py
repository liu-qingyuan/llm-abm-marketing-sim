#!/usr/bin/env python3
"""Offline gate and explicit runner for the v2 Formal robustness study."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn, cast

from llm_abm_sim import concurrent_robustness_formal_execution as _formal


class _CliFailure(ValueError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


_SAFE_CATEGORIES = {
    "formal_preflight_invalid",
    "authorization_invalid",
    "plan_invalid",
    "destination_invalid",
    "operator_error",
    "interrupted",
    "invalid_input",
}


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_request(path: Path) -> _formal.ConcurrentRobustnessFormalExecutionRequest:
    document, _payload = _formal._load_canonical_object(path, "Formal execution request")
    return _formal._request_from_plan(document)


def _lstat_is_symlink(path: Path) -> bool:
    try:
        return stat.S_ISLNK(path.lstat().st_mode)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _CliFailure("destination_invalid") from exc


def _reject_symlink_ancestors(path: Path) -> None:
    current = path
    while True:
        if _lstat_is_symlink(current):
            raise _CliFailure("destination_invalid")
        if current == current.parent:
            return
        current = current.parent


def _under(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _preflight_destination(
    request: _formal.ConcurrentRobustnessFormalExecutionRequest,
    request_path: Path,
    output_dir: Path,
    identity: Mapping[str, object],
) -> Path:
    target = Path(os.path.abspath(output_dir.expanduser()))
    _reject_symlink_ancestors(target)
    if target.exists() or target.is_symlink():
        raise _CliFailure("destination_invalid")
    if not target.parent.is_dir() or _lstat_is_symlink(target.parent):
        raise _CliFailure("destination_invalid")

    protected_files = {
        request_path.absolute(), request.manifest.path,
        *(row.path for row in request.qualification_artifacts),
    }
    # Use the source identity already closed by readiness, without repeating
    # external validation or inventing a second manifest/source interpretation.
    source = cast(Mapping[str, object], identity["source"])
    protected_roots = {
        request.output_root, Path(cast(str, source["source_root"])),
        *(row.path.parent for row in request.qualification_artifacts),
    }
    if any(target == path for path in protected_files) or any(
        _under(target, root) or _under(root, target) for root in protected_roots
    ):
        raise _CliFailure("destination_invalid")
    return target


def _write_readonly_canonical(path: Path, document: object) -> None:
    payload = _canonical_json_bytes(document)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError as exc:
        # Deliberately do not unlink a partial file. The directory remains
        # visibly non-ready and an operator can reconcile it safely.
        raise _CliFailure("destination_invalid") from exc


def _write_preflight_artifacts(
    output_dir: Path,
    *,
    request_payload: bytes,
    readiness: Mapping[str, object],
) -> None:
    try:
        output_dir.mkdir(mode=0o755, exist_ok=False)
    except OSError as exc:
        raise _CliFailure("destination_invalid") from exc

    template = cast(Mapping[str, object], readiness["authorization_template"])
    handoff = cast(Mapping[str, object], readiness["operational_issue_handoff"])
    audit = {
        "schema_version": "concurrent-robustness-formal-preflight-audit-v1",
        "status": "ready_for_human",
        "checked_at_utc": _formal._utc_now().isoformat(),
        "request_sha256": _sha256_bytes(request_payload),
        "request_identity_sha256": readiness["request_identity_sha256"],
        "readiness_sha256": readiness["readiness_sha256"],
        "provider_calls": 0,
        "credential_reads": 0,
        "authorization": False,
        "live_api_triggered": False,
        "raw_inputs_persisted": False,
    }
    _write_readonly_canonical(output_dir / "formal-readiness.json", readiness)
    _write_readonly_canonical(output_dir / "formal-authorization-template.json", template)
    body = handoff.get("body")
    if not isinstance(body, str):
        raise _CliFailure("formal_preflight_invalid")
    try:
        handoff_path = output_dir / "operational-issue-handoff.md"
        with handoff_path.open("x", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        handoff_path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError as exc:
        raise _CliFailure("destination_invalid") from exc
    # Last-file marker: a partially written bundle must not advertise readiness.
    _write_readonly_canonical(output_dir / "preflight-audit.json", audit)


def _summary(plan: Mapping[str, object]) -> dict[str, object]:
    identity = plan.get("request_identity")
    output_identity = None
    formal_scope = None
    if isinstance(identity, Mapping):
        output_identity = identity.get("output_identity")
        formal_scope = identity.get("formal_run_scope")
    return {
        "status": plan.get("status"),
        "output_identity": output_identity,
        "formal_run_scope": formal_scope,
        "plan_identity_sha256": plan.get("plan_identity_sha256"),
        "request_identity_sha256": plan.get("request_identity_sha256"),
        "readiness_sha256": plan.get("readiness_sha256"),
        "authorization_sha256": plan.get("authorization_sha256"),
    }


def _preflight(args: argparse.Namespace) -> dict[str, object]:
    request_path = Path(args.request)
    document, request_payload = _formal._load_canonical_object(
        request_path, "Formal execution request"
    )
    try:
        request = _formal._request_from_plan(document)
    except _formal.ConcurrentRobustnessFormalPreflightError as exc:
        raise _CliFailure("formal_preflight_invalid") from exc
    try:
        readiness = _formal.authorization_readiness(request)
    except Exception as exc:
        raise _CliFailure("formal_preflight_invalid") from exc
    # All validation, including the source and qualification closure, is done
    # before creating the new directory or any output file.
    output_dir = _preflight_destination(
        request, request_path, Path(args.output_dir),
        cast(Mapping[str, object], readiness["request_identity"]),
    )
    _write_preflight_artifacts(output_dir, request_payload=request_payload, readiness=readiness)
    return {
        "status": readiness["status"],
        "request_identity_sha256": readiness["request_identity_sha256"],
        "readiness_sha256": readiness["readiness_sha256"],
    }


def _authorize(args: argparse.Namespace) -> dict[str, object]:
    request = _load_request(Path(args.request))
    try:
        plan = _formal.authorize_formal_execution(
            request=request,
            authorization_path=Path(args.authorization),
            authorization_sha256=args.authorization_sha256,
            plan_output=Path(args.plan_output),
        )
    except _formal.ConcurrentRobustnessFormalPreflightError as exc:
        raise _CliFailure("authorization_invalid") from exc
    return _summary(plan)


def _check_plan(args: argparse.Namespace) -> dict[str, object]:
    plan_path = Path(args.plan)
    try:
        plan = _formal.validate_formal_execution_plan(plan_path)
    except (KeyError, _formal.ConcurrentRobustnessFormalPreflightError, ValueError) as exc:
        raise _CliFailure("plan_invalid") from exc
    return _summary(plan)


def _run(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    # Keep the parent import lazy: the composition root is the only owner of
    # the runtime gate, clients, locks, and study lifecycle.
    from llm_abm_sim.concurrent_robustness_operator import (
        run_concurrent_robustness_formal,
    )

    result = run_concurrent_robustness_formal(Path(args.plan))
    dumped = result.model_dump(mode="json")
    status = dumped.get("status")
    if status in {"complete", "resumable"}:
        return cast(dict[str, object], dumped), 0
    return cast(dict[str, object], dumped), 1


def _recovery_epoch(args: argparse.Namespace) -> dict[str, object]:
    from llm_abm_sim import concurrent_robustness_recovery as proposals
    from llm_abm_sim import concurrent_robustness_recovery_epoch as epoch

    if args.command == "inspect-recovery-epoch":
        return epoch.inspect_recovery_initial_epoch_plan(args.plan)
    path = proposals._safe_path(args.request)
    proposals._file_fact(path)
    document, _ = _formal._load_canonical_object(path, "initial recovery epoch request")
    request = epoch.RecoveryInitialEpochRequest.model_validate(document)
    if args.command == "prepare-recovery-epoch":
        return epoch.prepare_recovery_initial_epoch(request)
    plan = epoch.authorize_recovery_initial_epoch(
        request=request, authorization_path=args.authorization,
        authorization_sha256=args.authorization_sha256, plan_output=args.plan_output,
    )
    return {key: plan[key] for key in (
        "schema_version", "plan_path", "plan_identity_sha256", "initial_epoch_only",
        "execution_authority", "recovery_slots_consumed",
    )}


def _recovery_execution(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    from llm_abm_sim import concurrent_robustness_recovery as proposals
    from llm_abm_sim import concurrent_robustness_recovery_execution as recovery

    if args.command == "status-recovery":
        return recovery.inspect_recovery_execution(args.plan), 0
    if args.command == "inspect-recovery-bundle":
        return recovery.inspect_recovery_execution_bundle(args.bundle), 0
    if args.command == "run-recovery":
        from llm_abm_sim.concurrent_robustness_operator import run_concurrent_robustness_recovery

        result = run_concurrent_robustness_recovery(args.plan)
        return result.model_dump(mode="json"), 0 if result.recovery_status in {"complete", "checkpoint"} else 2
    path = proposals._safe_path(args.request)
    proposals._file_fact(path)
    document, _ = _formal._load_canonical_object(path, "recovery execution request")
    request = recovery.RecoveryExecutionRequest.model_validate(document)
    if args.command == "prepare-recovery-execution":
        return recovery.prepare_recovery_execution(request), 0
    plan = recovery.authorize_recovery_execution(request=request, authorization_path=args.authorization,
        authorization_sha256=args.authorization_sha256, plan_output=args.plan_output)
    return {key: plan[key] for key in ("schema_version", "plan_path", "plan_identity_sha256", "execution_authority")}, 0


def _error_category(stage: str, exc: BaseException) -> str:
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted"
    if isinstance(exc, _CliFailure) and exc.category in _SAFE_CATEGORIES:
        return exc.category
    if stage in {"run", "run-recovery"}:
        return "operator_error"
    if stage in {"prepare-recovery-execution", "authorize-recovery-execution", "status-recovery", "inspect-recovery-bundle"}:
        return "recovery_execution_invalid"
    if stage == "status":
        return "inspection_invalid"
    if stage in {"prepare-recovery", "inspect-recovery"}:
        return "recovery_invalid"
    if stage in {"prepare-recovery-epoch", "authorize-recovery-epoch", "inspect-recovery-epoch"}:
        return "recovery_epoch_invalid"
    return "invalid_input"


def _emit(value: Mapping[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse normally echoes offending arguments, which may be sensitive.
        raise _CliFailure("invalid_input")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description="Concurrent Robustness v2 Formal gate and runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--request", type=Path, required=True)
    preflight.add_argument("--output-dir", type=Path, required=True)

    authorize = subparsers.add_parser("authorize")
    authorize.add_argument("--request", type=Path, required=True)
    authorize.add_argument("--authorization", type=Path, required=True)
    authorize.add_argument("--authorization-sha256", required=True)
    authorize.add_argument("--plan-output", type=Path, required=True)

    check_plan = subparsers.add_parser("check-plan")
    check_plan.add_argument("--plan", type=Path, required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--plan", type=Path, required=True)

    recovery = subparsers.add_parser("prepare-recovery")
    recovery.add_argument("--plan", type=Path, required=True)
    recovery.add_argument("--output-dir", type=Path, required=True)

    inspect_recovery = subparsers.add_parser("inspect-recovery")
    inspect_recovery.add_argument("--proposal", type=Path, required=True)

    epoch = subparsers.add_parser("prepare-recovery-epoch")
    epoch.add_argument("--request", type=Path, required=True)

    authorize_epoch = subparsers.add_parser("authorize-recovery-epoch")
    authorize_epoch.add_argument("--request", type=Path, required=True)
    authorize_epoch.add_argument("--authorization", type=Path, required=True)
    authorize_epoch.add_argument("--authorization-sha256", required=True)
    authorize_epoch.add_argument("--plan-output", type=Path, required=True)

    inspect_epoch = subparsers.add_parser("inspect-recovery-epoch")
    inspect_epoch.add_argument("--plan", type=Path, required=True)

    recovery_execution = subparsers.add_parser("prepare-recovery-execution")
    recovery_execution.add_argument("--request", type=Path, required=True)
    recovery_authorize = subparsers.add_parser("authorize-recovery-execution")
    recovery_authorize.add_argument("--request", type=Path, required=True)
    recovery_authorize.add_argument("--authorization", type=Path, required=True)
    recovery_authorize.add_argument("--authorization-sha256", required=True)
    recovery_authorize.add_argument("--plan-output", type=Path, required=True)
    for command in ("status-recovery", "run-recovery"):
        entry = subparsers.add_parser(command)
        entry.add_argument("--plan", type=Path, required=True)
    bundle = subparsers.add_parser("inspect-recovery-bundle")
    bundle.add_argument("--bundle", type=Path, required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--plan", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    stage = "arguments"
    try:
        args = _parser().parse_args(argv)
        stage = cast(str, args.command)
        if stage == "preflight":
            result = _preflight(args)
            exit_code = 0
        elif stage == "authorize":
            result = _authorize(args)
            exit_code = 0
        elif stage == "check-plan":
            result = _check_plan(args)
            exit_code = 0
        elif stage == "status":
            from llm_abm_sim.concurrent_robustness_operator import inspect_concurrent_robustness_formal

            result = inspect_concurrent_robustness_formal(args.plan)
            exit_code = 0
        elif stage == "prepare-recovery":
            from llm_abm_sim.concurrent_robustness_recovery import prepare_concurrent_robustness_recovery

            proposal = prepare_concurrent_robustness_recovery(args.plan, output_dir=args.output_dir)
            result = {key: proposal[key] for key in (
                "status", "proposal_identity_sha256", "output_root", "remaining_valid_judgments",
                "maximum_new_physical_attempts", "execution_authority", "provider_calls_during_preparation",
                "credential_reads_during_preparation", "current_gate_at_preparation",
            )}
            exit_code = 0
        elif stage == "inspect-recovery":
            from llm_abm_sim.concurrent_robustness_recovery import inspect_concurrent_robustness_recovery_proposal

            result = inspect_concurrent_robustness_recovery_proposal(args.proposal)
            exit_code = 0
        elif stage in {"prepare-recovery-epoch", "authorize-recovery-epoch", "inspect-recovery-epoch"}:
            result = _recovery_epoch(args)
            exit_code = 0
        elif stage in {"prepare-recovery-execution", "authorize-recovery-execution", "status-recovery", "inspect-recovery-bundle", "run-recovery"}:
            result, exit_code = _recovery_execution(args)
        else:
            result, exit_code = _run(args)
        _emit(result)
        return exit_code
    except KeyboardInterrupt as exc:
        _emit({"status": "error", "stage": stage, "category": _error_category(stage, exc)})
        return 130
    except Exception as exc:
        _emit({"status": "error", "stage": stage, "category": _error_category(stage, exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
