from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .concurrent_robustness_recovery_execution import RecoveryExecutionResult

from .concurrent_robustness_formal_execution import (
    _manifest_from_request,
    _request_from_plan,
    inspect_formal_execution_plan,
    validate_formal_execution_plan,
)
from .concurrent_robustness_study import (
    ConcurrentRobustnessStudy,
    ConcurrentRobustnessStudyResult,
    ConcurrentRobustnessStudyStatus,
)
from .concurrent_robustness_v2 import ConcurrentRobustnessManifestV2, _inspect_v2_progress, _PromptModelCell
from .decision import LLMDecisionAdapter
from .providers.antigravity import AntigravityGeminiProviderClient
from .providers.openai_compatible import _OpenAISDKClient
from .providers.pi_subscription import PiKimiSubscriptionProviderClient, PiSubscriptionProviderClient
from .providers.robustness import (
    AntigravityGeminiDecisionAdapter,
    DeepSeekV4FlashDecisionAdapter,
    PiKimiDecisionAdapter,
    PiOpenAIDecisionAdapter,
)

_Transport = _OpenAISDKClient | AntigravityGeminiProviderClient | PiSubscriptionProviderClient


class ConcurrentRobustnessOperatorError(RuntimeError):
    """The local Operator refused setup without exposing supplied values."""


@contextmanager
def _exclusive_output(output: Path) -> Iterator[None]:
    # Keep the lock outside Study's immutable inventory. Never unlink it: another
    # process could otherwise lock a different inode for the same output root.
    if output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
        raise ConcurrentRobustnessOperatorError("Output lock requires non-symlink paths")
    lock_path = output.with_name(f".{output.name}.v2-operator.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != 0:
            raise ConcurrentRobustnessOperatorError("Output lock must be a dedicated regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ConcurrentRobustnessOperatorError("Formal output is already in use") from None
        yield
    finally:
        os.close(descriptor)


def _runtime_credential(name: str) -> str:
    value = os.environ.get(name)
    if not value or not value.strip():
        raise ConcurrentRobustnessOperatorError("Required runtime Provider credential is unavailable")
    return value


def _new_client(model: str, timeout: float) -> _Transport:
    if model == "kimi-coding/k3-256k":
        return PiKimiSubscriptionProviderClient(response_timeout_seconds=timeout)
    if model == "openai-codex/gpt-5.6-sol":
        return PiSubscriptionProviderClient(response_timeout_seconds=timeout)
    # OpenAI's optional dependency owns HTTPX. Never inherit a proxy or SSL env
    # override that silently changes the explicitly qualified transport route.
    import httpx

    credential = _runtime_credential(
        "DEEPSEEK_API_KEY" if model == "deepseek-v4-flash" else "ANTIGRAVITY_API_KEY"
    )
    http_client = httpx.Client(timeout=timeout, trust_env=False)
    try:
        if model == "deepseek-v4-flash":
            return _OpenAISDKClient(
                api_key=credential, base_url="https://api.deepseek.com", timeout=timeout,
                wire_api="chat", chat_output_token_field="max_tokens", http_client=http_client,
            )
        return AntigravityGeminiProviderClient(
            api_key=credential, base_url="http://127.0.0.1:8045/v1", timeout=timeout,
            http_client=http_client,
        )
    except BaseException:
        http_client.close()
        raise


def _adapter_for_cell(cell: _PromptModelCell, client: _Transport, *, kimi_output_token_ceiling: int = 256) -> LLMDecisionAdapter:
    model = cell.requested_model
    if model == "deepseek-v4-flash":
        return DeepSeekV4FlashDecisionAdapter(prompt_version=cell.prompt_version, client=client)
    if model in {"gemini-3.1-pro", "gemini-3.8-flash-high"}:
        return AntigravityGeminiDecisionAdapter(requested_model=model, prompt_version=cell.prompt_version, client=client)
    if model == "kimi-coding/k3-256k":
        return PiKimiDecisionAdapter(prompt_version=cell.prompt_version, client=client, output_token_ceiling=kimi_output_token_ceiling)
    return PiOpenAIDecisionAdapter(prompt_version=cell.prompt_version, client=client)


@contextmanager
def _task_model_resources(manifest: ConcurrentRobustnessManifestV2, timeout: float,
                          model: str, *, maximum_inflight: int = 1, kimi_output_token_ceiling: int = 256) -> Iterator[Callable[[], dict[str, LLMDecisionAdapter]]]:
    cells = tuple(cell for cell in manifest.prompt_model_cells if cell.requested_model == model)
    if not cells:
        raise ConcurrentRobustnessOperatorError("Task requested an unknown model")
    if (type(maximum_inflight) is not int or not 1 <= maximum_inflight <= 10
        or (model != "kimi-coding/k3-256k" and maximum_inflight != 1
            and not (model == "gemini-3.1-pro" and maximum_inflight == 4))):
        raise ConcurrentRobustnessOperatorError("Parallel resources require the approved model capacity")
    with ExitStack() as resources:
        clients = []
        for _ in range(maximum_inflight):
            client = _new_client(model, timeout)
            resources.callback(client.close)
            clients.append(client)
        def fresh() -> dict[str, LLMDecisionAdapter]:
            if maximum_inflight == 1:
                return {cell.cell_id: _adapter_for_cell(cell, clients[0], kimi_output_token_ceiling=kimi_output_token_ceiling) for cell in cells}
            from ._concurrent_recovery_parallel_runtime import ParallelAdapterPool, preflight_pools
            pools: dict[str, LLMDecisionAdapter] = {cell.cell_id: ParallelAdapterPool(tuple(
                _adapter_for_cell(cell, client, kimi_output_token_ceiling=kimi_output_token_ceiling) for client in clients)) for cell in cells}
            preflight_pools(manifest, cells, pools, kimi_output_token_ceiling=kimi_output_token_ceiling)
            return pools
        yield fresh



def _build_adapters(
    manifest: ConcurrentRobustnessManifestV2, timeout: float, resources: ExitStack,
) -> dict[str, LLMDecisionAdapter]:
    clients: dict[str, _Transport] = {}
    adapters: dict[str, LLMDecisionAdapter] = {}
    for cell in manifest.prompt_model_cells:
        model = cell.requested_model
        if model not in clients:
            client = _new_client(model, timeout)
            resources.callback(client.close)
            clients[model] = client
        adapters[cell.cell_id] = _adapter_for_cell(cell, clients[model])
    return adapters


def inspect_concurrent_robustness_formal(plan_path: str | Path) -> dict[str, object]:
    """Read verified progress and expiry blockers without credentials or writes.

    This never renews authorization, resumes a stopped pair or enables Provider
    dispatch. Remaining attempts alone are not recovery permission.
    """
    inspected = inspect_formal_execution_plan(plan_path)
    snapshot = _inspect_v2_progress(
        manifest=inspected.manifest, output_path=inspected.request.output_root,
        formal_execution_plan=inspected.plan,
    )
    blockers = []
    if not inspected.current_gate["currently_valid"]:
        blockers.append("authorization_or_qualification_not_current")
    if snapshot["status"] == "stopped":
        blockers.append("stopped_run_requires_explicit_recovery_contract")
    if snapshot["status"] == "reconciliation_required":
        blockers.append("unknown_postdispatch_requires_reconciliation")
    return {
        "schema_version": "concurrent-robustness-formal-inspection-v1",
        **snapshot, "current_gate": inspected.current_gate, "blockers": blockers,
        "plan_identity_sha256": inspected.plan["plan_identity_sha256"],
        "inspection_only": True, "automatic_resume_allowed": False,
        "provider_calls_during_inspection": 0, "credential_reads_during_inspection": 0,
        "production_deploy_eligible": False,
    }


def run_concurrent_robustness_formal(plan_path: str | Path) -> ConcurrentRobustnessStudyResult:
    """Run at most one model; only Study owns retry, stop, resume and publication.

    Credentials are runtime-injected only after plan, live and source/status
    gates. This function never refreshes qualifications or creates authorization.
    """
    plan = validate_formal_execution_plan(plan_path)
    request = _request_from_plan(plan["request"])
    manifest, _ = _manifest_from_request(request)
    if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1":
        raise ConcurrentRobustnessOperatorError("Formal Operator requires the explicit live gate")
    with _exclusive_output(request.output_root):
        study = ConcurrentRobustnessStudy()
        inspected = study.run(manifest, None, request.output_root, formal_execution_plan=plan_path)
        if inspected.status in {
            ConcurrentRobustnessStudyStatus.COMPLETE,
            ConcurrentRobustnessStudyStatus.STOPPED,
            ConcurrentRobustnessStudyStatus.RECONCILIATION_REQUIRED,
        }:
            return inspected
        try:
            with ExitStack() as resources:
                adapters = _build_adapters(manifest, request.run_parameters.request_timeout_seconds, resources)
                return study.run(manifest, adapters, request.output_root, formal_execution_plan=plan_path)
        except Exception:
            # SDK/worker setup or cleanup errors may contain raw values. Durable
            # attempt provenance, if any, remains owned by Study; never infer zero.
            raise ConcurrentRobustnessOperatorError("Provider setup or execution failed closed") from None


def run_concurrent_robustness_recovery(plan_path: str | Path) -> RecoveryExecutionResult:
    """One explicitly approved recovery model, under the original source lock.

    Qualification refresh and new approval are separate operations. A terminal
    campaign can publish its frozen checkpoint with zero client construction.
    """
    from . import concurrent_robustness_formal_execution as formal
    from . import concurrent_robustness_recovery_execution as recovery
    from ._concurrent_recovery_bundle import publish_recovery_bundle
    from ._concurrent_recovery_campaign import recovery_scope

    context = recovery._load_context(plan_path)
    if context.origins.task_plan is not None:
        raise ConcurrentRobustnessOperatorError("Derived task epochs require the single task entry")
    action = recovery._action(context)
    if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1":
        raise ConcurrentRobustnessOperatorError("Formal Operator requires the explicit live gate")
    if action != "return" and not recovery._window_current(context.plan, formal._utc_now()):
        raise ConcurrentRobustnessOperatorError("Recovery authorization or qualifications are not current")
    with recovery_scope(context.origins.campaign):
        context = recovery._load_context(plan_path)
        if recovery._action(context) == "return":
            return recovery._result(context, publish_recovery_bundle(context))
        if not recovery._window_current(context.plan, formal._utc_now()):
            raise ConcurrentRobustnessOperatorError("Recovery authorization or qualifications are not current")
        manifest = recovery.RecoveryExecutionManifest(execution_plan=formal.FormalArtifactReference(
            path=Path(context.plan["plan_path"]), sha256=formal._sha256_file(Path(context.plan["plan_path"])),
        ))
        try:
            with ExitStack() as resources:
                adapters = _build_adapters(context.origins.source.manifest,
                    context.origins.source.request.run_parameters.request_timeout_seconds, resources)
                result = ConcurrentRobustnessStudy().run(manifest, adapters, context.journal.root)
                if not isinstance(result, recovery.RecoveryExecutionResult):
                    raise ConcurrentRobustnessOperatorError("Recovery Study returned an incompatible result")
                return result
        except Exception:
            raise ConcurrentRobustnessOperatorError("Recovery setup or execution failed closed") from None


@dataclass(frozen=True)
class _TaskReportHandoff:
    report_path: Path
    formal_evidence_closed: bool


def _publish_task_report(bundle: Path, destination: Path) -> _TaskReportHandoff:
    """Only the independent Report reader can attest Formal closure."""
    from importlib import import_module

    from .concurrent_robustness_formal_execution import _sha256_file

    report = import_module(".concurrent_robustness_recovery_report", __package__)
    path = report.export_concurrent_robustness_recovery_report(bundle, output_dir=destination)
    facts = report.inspect_concurrent_robustness_recovery_report(path)
    if (facts.get("source_bundle") != {"path": str(bundle), "sha256": _sha256_file(bundle)}
            or facts.get("formal_evidence_closed") is not True or facts.get("report_status") != "complete"):
        raise ConcurrentRobustnessOperatorError("Report closure differs from the execution checkpoint")
    return _TaskReportHandoff(path, True)


def run_concurrent_robustness_recovery_task(plan_path: str | Path) -> dict[str, object]:
    """Run one approved task, automatically advancing its internal model epochs.

    Only unfinished models construct clients. Self-checks and Formal calls are
    admitted by Study under the same source lock and durable cumulative ledger.
    Report-only continuation needs neither credentials, a live gate nor renewed
    approval; a failed/unavailable report never restarts Provider execution.
    """
    from . import concurrent_robustness_recovery_task as task
    from ._concurrent_recovery_campaign import recovery_scope
    from ._concurrent_recovery_task_runtime import _TERMINAL

    context = task._context(plan_path)
    status = task._task_status(context)
    if status["status"] not in _TERMINAL and context.state.kimi_migration_active:
        raise ConcurrentRobustnessOperatorError("Activated Kimi migration requires its official Operator")
    if status["status"] not in _TERMINAL and os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1":
        raise ConcurrentRobustnessOperatorError("Formal Operator requires the explicit live gate")
    try:
        with recovery_scope(context.origins.campaign):
            result = ConcurrentRobustnessStudy().run_task(plan_path, model_resources=lambda model:
                _task_model_resources(context.origins.source.manifest,
                    context.origins.source.request.run_parameters.request_timeout_seconds, model,
                    maximum_inflight=context.state.effective_parallel_approval["maximum_inflight"]
                    if context.state.effective_parallel_approval is not None else 1,
                    kimi_output_token_ceiling=context.state.output_amendment["output_token_ceiling"]
                    if context.state.output_amendment is not None else 256))
    except Exception:
        raise ConcurrentRobustnessOperatorError("Recovery task setup or execution failed closed") from None
    if result["status"] == "execution_complete":
        try:
            destination = Path(context.plan["request"]["report_destination"])
            handoff = _publish_task_report(Path(result["execution_bundle"]), destination)
            if (not isinstance(handoff, _TaskReportHandoff) or handoff.report_path != destination / "report.html"
                    or not handoff.report_path.is_file()):
                raise ConcurrentRobustnessOperatorError("Recovery Report returned an incompatible artifact")
            result.update(status="complete", report_status="complete", report_path=str(handoff.report_path),
                          formal_evidence_closed=handoff.formal_evidence_closed)
        except Exception:
            result.update(report_status="report_pending", report_failure="evidence_or_report_unavailable_or_failed")
    return result


def run_concurrent_robustness_kimi_official(plan_path: str | Path, *, api_key: str) -> dict[str, object]:
    """Run only the admitted official migration, at most five independent requests.

    Runtime credentials are neither saved nor sourced from an environment file.
    Study retains the original source lock, successes, failure history, cash and
    physical limits. A subsequent hard stop or completed model is read-only.
    """
    from . import concurrent_robustness_recovery_task as task
    from ._concurrent_recovery_bundle import publish_recovery_bundle
    from ._concurrent_recovery_campaign import CampaignJournal, recovery_scope
    from ._concurrent_recovery_kimi_migration import MODEL, preflight
    from ._concurrent_recovery_parallel_runtime import ParallelAdapterPool
    from ._concurrent_recovery_task_runtime import _TERMINAL
    from .providers.moonshot import MoonshotOfficialClient
    from .providers.robustness import OfficialKimiDecisionAdapter

    context = task._context(plan_path)
    with recovery_scope(context.origins.campaign):
        context = task._context(plan_path)
        state = context.state
        if state.kimi_migration_approval is None:
            raise ConcurrentRobustnessOperatorError("Official Kimi requires its accepted migration receipt")
        status = task._task_status(context)
        if state.kimi_migration_active and status["status"] in _TERMINAL:
            publish_recovery_bundle(context)
            return task._task_status(context)
        if not status["authorization_current"] or os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1":
            raise ConcurrentRobustnessOperatorError("Official Kimi requires its current explicit live window")
        manifest = context.origins.source.manifest
        cells = tuple(c for c in manifest.prompt_model_cells if c.requested_model == MODEL)
        with ExitStack() as resources:
            clients = [resources.enter_context(MoonshotOfficialClient(api_key=api_key, live_enabled=True)) for _ in range(5)]
            def fresh() -> dict[str, LLMDecisionAdapter]:
                return {c.cell_id: ParallelAdapterPool(tuple(OfficialKimiDecisionAdapter(prompt_version=c.prompt_version, client=x)
                        for x in clients)) for c in cells}
            preflight(state, manifest, fresh())
            if not state.kimi_migration_active:
                journal = CampaignJournal.open(context.origins.campaign)
                if journal.head != context.journal.head:
                    raise ConcurrentRobustnessOperatorError("Official migration head changed before activation")
                state.append(journal, "kimi_official_execution_activated", {"approval": state.kimi_migration_approval["approval"]})
            @contextmanager
            def model_resources(model: str) -> Iterator[Callable[[], dict[str, LLMDecisionAdapter]]]:
                if model != MODEL:
                    raise ConcurrentRobustnessOperatorError("Official Kimi resources exclude every other model")
                yield fresh
            return ConcurrentRobustnessStudy().run_task(plan_path, model_resources=model_resources)
