from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from .concurrent_robustness_formal_execution import (
    _manifest_from_request,
    _request_from_plan,
    validate_formal_execution_plan,
)
from .concurrent_robustness_study import (
    ConcurrentRobustnessStudy,
    ConcurrentRobustnessStudyResult,
    ConcurrentRobustnessStudyStatus,
)
from .concurrent_robustness_v2 import ConcurrentRobustnessManifestV2
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
        client = clients[model]
        adapter: LLMDecisionAdapter
        if model == "deepseek-v4-flash":
            adapter = DeepSeekV4FlashDecisionAdapter(prompt_version=cell.prompt_version, client=client)
        elif model in {"gemini-3.1-pro", "gemini-3.8-flash-high"}:
            adapter = AntigravityGeminiDecisionAdapter(
                requested_model=model, prompt_version=cell.prompt_version, client=client,
            )
        elif model == "kimi-coding/k3-256k":
            adapter = PiKimiDecisionAdapter(prompt_version=cell.prompt_version, client=client)
        else:
            adapter = PiOpenAIDecisionAdapter(prompt_version=cell.prompt_version, client=client)
        adapters[cell.cell_id] = adapter
    return adapters


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
