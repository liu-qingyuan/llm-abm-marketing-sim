from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal_module
from llm_abm_sim import concurrent_robustness_operator as operator_module
from llm_abm_sim.concurrent_robustness_formal_execution import (
    ConcurrentRobustnessFormalPreflightError,
    authorize_formal_execution,
)
from llm_abm_sim.concurrent_robustness_operator import (
    ConcurrentRobustnessOperatorError,
    run_concurrent_robustness_formal,
)
from llm_abm_sim.concurrent_robustness_study import (
    ConcurrentRobustnessError,
    ConcurrentRobustnessErrorCode,
    ConcurrentRobustnessStudyResult,
    ConcurrentRobustnessStudyStatus,
)
from llm_abm_sim.provider_accounting import ProviderResponseEnvelope
from tests.unit.test_concurrent_robustness_formal_execution import (
    _NOW,
    _authorization_artifact,
    _request_bundle,
)
from tests.unit.test_robustness_provider_adapters import _context


def _plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    request, _ = _request_bundle(tmp_path)
    monkeypatch.setattr(formal_module, "_utc_now", lambda: _NOW)
    path, digest, _ = _authorization_artifact(tmp_path, request)
    plan = tmp_path / "plan.json"
    authorize_formal_execution(
        request=request, authorization_path=path, authorization_sha256=digest, plan_output=plan,
    )
    return plan


class _Transport:
    external_provider_client = True
    wire_api = "chat_completions"
    thinking_budget = 128
    reasoning_usage_mapping = "reasoning_included_in_completion_tokens"
    output_token_ceiling_scope = "visible_completion_tokens"
    wire_output_token_ceiling = 1024
    last_output_tokens_for_ceiling = 10

    def __init__(self, kind: str, settings: dict[str, Any]) -> None:
        self.kind = kind
        self.settings = settings
        self.calls: list[dict[str, Any]] = []
        self.closed = 0
        self.provider_transport = (
            "antigravity_openai_compatible_gateway" if kind == "gemini"
            else "kimi-coding" if kind == "kimi" else "openai-codex"
        )
        self.output_token_ceiling_enforcement = (
            "wire_total_and_visible_application_fail_closed" if kind == "gemini"
            else "wire_and_application_fail_closed" if kind == "kimi" else "application_fail_closed"
        )

    def create_response(self, messages: list[dict[str, str]], model: str, **settings: Any) -> ProviderResponseEnvelope:
        self.calls.append({"model": model, "messages": messages, **settings})
        return ProviderResponseEnvelope(
            decision_text='{"engage":true,"probability":0.8,"reason":"fit","confidence":0.9,"action":"like"}',
            observed_model=model.rsplit("/", 1)[-1], observed_model_status="reported", usage_status="complete",
            input_tokens=20, output_tokens=10, total_tokens=30, cached_input_tokens=0,
        )

    def close(self) -> None:
        self.closed += 1
        if "http_client" in self.settings:
            self.settings["http_client"].close()


def _clients(monkeypatch: pytest.MonkeyPatch) -> list[_Transport]:
    created: list[_Transport] = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek")
    monkeypatch.setenv("ANTIGRAVITY_API_KEY", "test-only-local-gateway")
    for name, kind in (
        ("_OpenAISDKClient", "deepseek"),
        ("AntigravityGeminiProviderClient", "gemini"),
        ("PiKimiSubscriptionProviderClient", "kimi"),
        ("PiSubscriptionProviderClient", "openai"),
    ):
        def factory(_kind: str = kind, **settings: Any) -> _Transport:
            transport = _Transport(_kind, settings)
            created.append(transport)
            return transport
        monkeypatch.setattr(operator_module, name, factory, raising=False)
    return created


def _result(manifest: Any, output: Path, status: str = "ready_for_human") -> ConcurrentRobustnessStudyResult:
    return ConcurrentRobustnessStudyResult(
        status=ConcurrentRobustnessStudyStatus(status), workspace_root=output, validation_report=output / "validation_report.json",
        manifest_sha256="a" * 64, logical_provider_attempts=0, physical_provider_attempts=0,
        study_root=output / "study-root" if status == "complete" else None,
    )


def test_operator_builds_twenty_fresh_adapters_and_closes_five_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    created = _clients(monkeypatch)
    stages: list[str] = []

    class Study:
        def run(self, manifest: Any, adapters: Any, output: Path, **kwargs: Any) -> ConcurrentRobustnessStudyResult:
            assert kwargs["formal_execution_plan"] == plan
            if adapters is None:
                stages.append("inspect")
                assert created == []
                return _result(manifest, output)
            stages.append("execute")
            assert list(adapters) == [cell.cell_id for cell in manifest.prompt_model_cells]
            assert len(adapters) == len({id(a) for a in adapters.values()}) == 20
            assert all(a.request_invocations == 0 for a in adapters.values())
            for cell in manifest.prompt_model_cells:
                adapter = adapters[cell.cell_id]
                assert adapter.request_evidence["requested_model"] == cell.requested_model
                assert adapter.prompt_version == cell.prompt_version
                if cell.prompt_variant == "P0":
                    assert adapter.decide(**_context()).action == "like"
            return _result(manifest, output, "resumable")

    monkeypatch.setattr(operator_module, "ConcurrentRobustnessStudy", Study)
    try:
        result = run_concurrent_robustness_formal(plan)
    except ConcurrentRobustnessOperatorError as error:
        # All values/transports in this composition test are synthetic.
        raise AssertionError(repr(error.__context__)) from None
    assert result.status == "resumable"
    assert stages == ["inspect", "execute"]
    assert [c.kind for c in created] == ["deepseek", "gemini", "gemini", "kimi", "openai"]
    assert all(c.closed == 1 for c in created)
    assert {k: v for k, v in created[0].settings.items() if k != "http_client"} == {
        "api_key": "test-only-deepseek", "base_url": "https://api.deepseek.com",
        "timeout": 30.0, "wire_api": "chat", "chat_output_token_field": "max_tokens",
    }
    assert all(c.settings["http_client"].is_closed for c in created[:3])
    assert all(c.settings["timeout"] == 30.0 for c in created[1:3])
    assert all(c.settings["response_timeout_seconds"] == 30.0 for c in created[3:])
    assert [c.calls[0]["model"] for c in created] == [
        "deepseek-v4-flash", "gemini-pro-agent", "gemini-3.8-flash-high", "kimi-coding/k3-256k", "gpt-5.6-sol",
    ]
    assert all(c.calls[0]["messages"] == created[0].calls[0]["messages"] for c in created)
    assert created[0].calls[0]["thinking_mode"] == "disabled"


@pytest.mark.parametrize("status", ["complete", "stopped", "reconciliation_required"])
def test_terminal_status_does_not_initialize_clients_or_read_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    created = _clients(monkeypatch)

    def denied(_name: str) -> str:
        pytest.fail("terminal status must not read credentials")

    class Study:
        def run(self, manifest: Any, adapters: Any, output: Path, **kwargs: Any) -> ConcurrentRobustnessStudyResult:
            assert adapters is None
            return _result(manifest, output, status)

    monkeypatch.setattr(operator_module, "ConcurrentRobustnessStudy", Study)
    monkeypatch.setattr(operator_module, "_runtime_credential", denied)
    assert run_concurrent_robustness_formal(plan).status == status
    assert created == []


@pytest.mark.parametrize("failure_stage", ["constructor", "execution", "interrupt"])
def test_clients_close_on_partial_setup_execution_error_and_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    created = _clients(monkeypatch)
    failed_http_clients: list[Any] = []
    original_factory = operator_module.AntigravityGeminiProviderClient

    def failing_factory(**settings: Any) -> Any:
        if len(created) == 2:
            failed_http_clients.append(settings["http_client"])
            raise RuntimeError("synthetic-raw-credential-sentinel")
        return original_factory(**settings)

    if failure_stage == "constructor":
        monkeypatch.setattr(operator_module, "AntigravityGeminiProviderClient", failing_factory)

    class Study:
        def run(self, manifest: Any, adapters: Any, output: Path, **kwargs: Any) -> ConcurrentRobustnessStudyResult:
            if adapters is None:
                return _result(manifest, output)
            if failure_stage == "interrupt":
                raise KeyboardInterrupt
            raise RuntimeError("synthetic-raw-credential-sentinel")

    monkeypatch.setattr(operator_module, "ConcurrentRobustnessStudy", Study)
    expected = KeyboardInterrupt if failure_stage == "interrupt" else ConcurrentRobustnessOperatorError
    with pytest.raises(expected) as captured:
        run_concurrent_robustness_formal(plan)
    assert "synthetic-raw-credential-sentinel" not in str(captured.value)
    assert len(created) == (2 if failure_stage == "constructor" else 5)
    assert all(c.closed == 1 and c.calls == [] for c in created)
    assert all(client.is_closed for client in failed_http_clients)


def test_expired_plan_cannot_read_credentials_or_initialize_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    created = _clients(monkeypatch)
    monkeypatch.setattr(formal_module, "_utc_now", lambda: _NOW + timedelta(days=2))
    with pytest.raises(ConcurrentRobustnessFormalPreflightError):
        run_concurrent_robustness_formal(plan)
    assert created == []


def test_output_lock_excludes_another_invocation_and_releases_after_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    created = _clients(monkeypatch)
    entered = 0

    class Study:
        def run(self, manifest: Any, adapters: Any, output: Path, **kwargs: Any) -> ConcurrentRobustnessStudyResult:
            nonlocal entered
            entered += 1
            assert adapters is None
            if entered == 1:
                with pytest.raises(ConcurrentRobustnessOperatorError, match="already in use"):
                    run_concurrent_robustness_formal(plan)
                raise RuntimeError("synthetic inspection interruption")
            return _result(manifest, output, "stopped")

    monkeypatch.setattr(operator_module, "ConcurrentRobustnessStudy", Study)
    with pytest.raises(RuntimeError, match="synthetic inspection interruption"):
        run_concurrent_robustness_formal(plan)
    assert entered == 1
    assert run_concurrent_robustness_formal(plan).status == "stopped"
    assert entered == 2
    assert created == []


def test_invalid_plan_rejects_before_any_setup_or_output(tmp_path: Path) -> None:
    plan = tmp_path / "invalid-plan.json"
    plan.write_text('{}\n', encoding="utf-8")
    plan.chmod(0o444)
    before = set(tmp_path.iterdir())
    with pytest.raises(ConcurrentRobustnessFormalPreflightError):
        run_concurrent_robustness_formal(plan)
    assert set(tmp_path.iterdir()) == before


def test_valid_plan_rechecks_source_before_clients_or_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    with pytest.raises(ConcurrentRobustnessError) as captured:
        run_concurrent_robustness_formal(plan)
    # Preflight fixture binds real hashes but intentionally is not a closed runtime source.
    assert captured.value.code is ConcurrentRobustnessErrorCode.INVALID_SOURCE
    assert not (tmp_path / "jinjiang-prompt-model-v2-formal-20300101T120000Z").exists()


def test_valid_plan_still_requires_live_gate_before_output_or_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    before = set(tmp_path.iterdir())
    with pytest.raises(ConcurrentRobustnessOperatorError, match="live gate"):
        run_concurrent_robustness_formal(plan)
    assert set(tmp_path.iterdir()) == before
