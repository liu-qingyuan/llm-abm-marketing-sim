from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

from llm_abm_sim.decision import ProviderResponseProvenanceUnknown
from llm_abm_sim.provider_accounting import ProviderResponseEnvelope
from llm_abm_sim.provider_request_contract import ReasoningEffortValue

PI_SUBSCRIPTION_ADAPTER_IDENTITY = "openai-codex-subscription-client-v1"
PI_SUBSCRIPTION_PROVIDER = "openai-codex"
PI_SUBSCRIPTION_MODEL_ALIASES: dict[str, str] = {
    "gpt-5.4-mini": "gpt-5.4-mini",
    "gpt-5.4-2026-03-05": "gpt-5.4",
    "gpt-5.5-2026-04-23": "gpt-5.5",
    "gpt-5.6-sol": "gpt-5.6-sol",
}


class PiSubscriptionProviderError(RuntimeError):
    """Raised when the explicit Pi subscription transport fails closed."""


class PiSubscriptionProviderClient:
    """External Provider client backed by the locally authenticated Pi subscription.

    The worker keeps OAuth material inside Pi's ModelRuntime. This Python process
    exchanges only Prompt text and allowlisted response evidence over a local pipe;
    neither side serializes credentials or raw Provider payloads.
    """

    external_provider_client = True
    provider_transport = PI_SUBSCRIPTION_PROVIDER
    output_token_ceiling_enforcement = "application_fail_closed"

    def __init__(
        self,
        *,
        worker_path: str | Path | None = None,
        response_timeout_seconds: float = 90.0,
        process_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1":
            raise PiSubscriptionProviderError(
                "Pi subscription Provider use requires the explicit LLM_ABM_RUN_LIVE_LLM=1 gate"
            )
        if response_timeout_seconds <= 0:
            raise ValueError("response_timeout_seconds must be positive")
        self.response_timeout_seconds = response_timeout_seconds
        self._process_factory = process_factory
        self._worker_path = Path(worker_path) if worker_path is not None else _default_worker_path()
        if not self._worker_path.is_file():
            raise PiSubscriptionProviderError("Pi subscription worker is not installed")
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._sequence = 0
        self._ready = False
        self.last_subscription_nominal_cost_usd = 0.0
        self.subscription_nominal_cost_usd_total = 0.0
        self._start()

    @property
    def ready(self) -> bool:
        return self._ready and self._process is not None and self._process.poll() is None

    @property
    def safe_metadata(self) -> dict[str, object]:
        return {
            "provider_transport": self.provider_transport,
            "adapter_identity": PI_SUBSCRIPTION_ADAPTER_IDENTITY,
            "authentication": "local_oauth_subscription",
            "requested_model_aliases": dict(PI_SUBSCRIPTION_MODEL_ALIASES),
            "output_token_ceiling_enforcement": self.output_token_ceiling_enforcement,
        }

    def create_response(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        reasoning_effort: ReasoningEffortValue | None = None,
        output_token_ceiling: int | None = None,
    ) -> ProviderResponseEnvelope:
        if reasoning_effort != "low":
            raise PiSubscriptionProviderError("Pi subscription robustness requests require reasoning_effort=low")
        if output_token_ceiling is None or output_token_ceiling < 1:
            raise PiSubscriptionProviderError("Pi subscription robustness requests require an output-token ceiling")
        upstream_model = PI_SUBSCRIPTION_MODEL_ALIASES.get(model)
        if upstream_model is None:
            raise PiSubscriptionProviderError("Pi subscription requested model is outside the approved allowlist")
        if not self.ready:
            self.close()
            self._start()
        response = self._rpc(
            {
                "type": "request",
                "messages": messages,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "output_token_ceiling": output_token_ceiling,
                "timeout_ms": int(self.response_timeout_seconds * 1000),
            }
        )
        usage = response.get("usage")
        if not isinstance(usage, dict):
            raise PiSubscriptionProviderError("Pi subscription response is missing usage evidence")
        if (
            response.get("provider") != PI_SUBSCRIPTION_PROVIDER
            or response.get("requested_model") != model
            or response.get("upstream_model") != upstream_model
            or response.get("output_token_ceiling_enforcement") != self.output_token_ceiling_enforcement
        ):
            raise PiSubscriptionProviderError("Pi subscription response identity is crossed")
        decision_text = response.get("decision_text")
        observed_model = response.get("observed_model")
        if not isinstance(decision_text, str) or observed_model != upstream_model:
            raise PiSubscriptionProviderError("Pi subscription response is missing or crossing model evidence")
        input_tokens = _non_negative_int(usage.get("input_tokens"), "input_tokens")
        output_tokens = _non_negative_int(usage.get("output_tokens"), "output_tokens")
        total_tokens = _non_negative_int(usage.get("total_tokens"), "total_tokens")
        cached_input_tokens = _non_negative_int(usage.get("cached_input_tokens"), "cached_input_tokens")
        if total_tokens != input_tokens + output_tokens or cached_input_tokens > input_tokens:
            raise PiSubscriptionProviderError("Pi subscription response usage totals are crossed")
        nominal_cost = _subscription_nominal_cost(usage.get("subscription_nominal_cost_usd"))
        self.last_subscription_nominal_cost_usd = nominal_cost
        self.subscription_nominal_cost_usd_total += nominal_cost
        return ProviderResponseEnvelope(
            decision_text=decision_text,
            observed_model=observed_model,
            observed_model_status="reported",
            usage_status="complete",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input_tokens,
        )

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._ready = False
            if process is None:
                return
            stdin = process.stdin
            if process.poll() is None:
                try:
                    if stdin is not None:
                        self._sequence += 1
                        stdin.write(json.dumps({"id": self._sequence, "type": "close"}) + "\n")
                        stdin.flush()
                    process.wait(timeout=2)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
            _close_pipe(process.stdin)
            _close_pipe(process.stdout)
            _close_pipe(process.stderr)

    def __enter__(self) -> PiSubscriptionProviderClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _start(self) -> None:
        pi_executable = shutil.which("pi")
        node_executable = shutil.which("node")
        if pi_executable is None or node_executable is None:
            raise PiSubscriptionProviderError("Pi subscription transport requires installed pi and node executables")
        package_root = Path(pi_executable).resolve().parents[1]
        env = dict(os.environ)
        env["PI_CODING_AGENT_PACKAGE_ROOT"] = str(package_root)
        env.setdefault("PI_AGENT_DIR", str(Path.home() / ".pi" / "agent"))
        try:
            process = self._process_factory(
                [node_executable, str(self._worker_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            raise PiSubscriptionProviderError("cannot start Pi subscription worker") from exc
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            raise PiSubscriptionProviderError("Pi subscription worker pipes are unavailable")
        self._process = process
        status = self._rpc({"type": "status"})
        models = status.get("models")
        if (
            status.get("provider") != PI_SUBSCRIPTION_PROVIDER
            or status.get("auth_type") != "oauth"
            or status.get("requested_model_aliases") != PI_SUBSCRIPTION_MODEL_ALIASES
            or not isinstance(models, list)
        ):
            self.close()
            raise PiSubscriptionProviderError("Pi subscription worker returned invalid OAuth readiness evidence")
        if tuple(models) != tuple(PI_SUBSCRIPTION_MODEL_ALIASES.values()):
            self.close()
            raise PiSubscriptionProviderError("Pi subscription worker does not expose the four required models")
        self._ready = True

    def _rpc(self, payload: dict[str, object]) -> dict[str, Any]:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                raise PiSubscriptionProviderError("Pi subscription worker is not running")
            assert process.stdin is not None
            assert process.stdout is not None
            self._sequence += 1
            request_id = self._sequence
            request = {"id": request_id, **payload}
            provider_request = payload.get("type") == "request"
            try:
                process.stdin.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                if provider_request:
                    raise ProviderResponseProvenanceUnknown(
                        "Pi subscription request dispatch could not be reconciled"
                    ) from exc
                raise PiSubscriptionProviderError("Pi subscription worker pipe failed") from exc
            try:
                line = _readline_with_timeout(process.stdout, self.response_timeout_seconds + 15.0)
            except PiSubscriptionProviderError as exc:
                self._discard_process(process)
                if provider_request:
                    raise ProviderResponseProvenanceUnknown(
                        "Pi subscription request timed out without verifiable response provenance"
                    ) from exc
                raise
            if not line:
                self._discard_process(process)
                if provider_request:
                    raise ProviderResponseProvenanceUnknown(
                        "Pi subscription request ended without verifiable response provenance"
                    )
                raise PiSubscriptionProviderError("Pi subscription worker stopped without a response")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                self._discard_process(process)
                if provider_request:
                    raise ProviderResponseProvenanceUnknown(
                        "Pi subscription request returned an unverifiable response"
                    ) from exc
                raise PiSubscriptionProviderError("Pi subscription worker returned malformed JSON") from exc
            if not isinstance(response, dict) or response.get("id") != request_id:
                self._discard_process(process)
                if provider_request:
                    raise ProviderResponseProvenanceUnknown(
                        "Pi subscription request response identity could not be reconciled"
                    )
                raise PiSubscriptionProviderError("Pi subscription worker response identity is crossed")
            if response.get("ok") is not True:
                error = response.get("error")
                detail = str(error)[:500] if error else "unknown external Provider failure"
                raise PiSubscriptionProviderError(detail)
            return response

    def _discard_process(self, process: subprocess.Popen[str]) -> None:
        self._ready = False
        if self._process is process:
            self._process = None
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        _close_pipe(process.stdin)
        _close_pipe(process.stdout)
        _close_pipe(process.stderr)

    def __del__(self) -> None:  # pragma: no cover - interpreter shutdown is best effort.
        try:
            self.close()
        except Exception:
            pass


def _default_worker_path() -> Path:
    return Path(__file__).resolve().parents[3] / "scripts" / "pi_subscription_provider_worker.mjs"


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PiSubscriptionProviderError(f"Pi subscription usage {label} is invalid")
    return value


def _subscription_nominal_cost(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) < float("inf"):
        raise PiSubscriptionProviderError("Pi subscription response reported invalid nominal cost")
    return float(value)


def _readline_with_timeout(stream: IO[Any], timeout_seconds: float) -> str:
    selector = selectors.DefaultSelector()
    try:
        selector.register(stream, selectors.EVENT_READ)
        if not selector.select(timeout_seconds):
            raise PiSubscriptionProviderError("Pi subscription worker response timed out")
        return stream.readline()
    finally:
        selector.close()


def _close_pipe(stream: IO[Any] | None) -> None:
    if stream is not None:
        try:
            stream.close()
        except OSError:
            pass
