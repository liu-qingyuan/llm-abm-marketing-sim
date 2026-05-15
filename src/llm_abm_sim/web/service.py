from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from llm_abm_sim.decision import EngageDecision, EngagementAction, LLMDecisionAdapter
from llm_abm_sim.provider_config import load_codex_provider_config, resolve_runtime_credential
from llm_abm_sim.providers.openai_compatible import ProviderConfigurationError
from llm_abm_sim.runner import ExperimentRunner
from llm_abm_sim.safe_serialization import safe_data
from llm_abm_sim.schemas import (
    FailClosedAction,
    PeerContext,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    ReportConfig,
    SimulationConfig,
    SimulationInput,
    SupportedLanguage,
    UserProfile,
)
from llm_abm_sim.web.imports import DatasetUpload, safe_dataset_validation_report

JobState = Literal["queued", "running", "succeeded", "failed", "blocked"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


ARTIFACT_ALLOWLIST = {
    "report.html",
    "report_payload.json",
    "graph_trace.json",
    "metrics_summary.json",
    "dataset_validation.json",
    "events.json",
    "run_result.json",
    "config.json",
    "step_records.csv",
    "input-builder.html",
}


@dataclass
class RunJob:
    run_id: str
    state: JobState = "queued"
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    progress_label: str = "queued"
    artifact_dir: Path | None = None
    error_class: str | None = None
    error_message: str | None = None
    mode: str = "product"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress_label": self.progress_label,
            "mode": self.mode,
            "artifact_dir": str(self.artifact_dir) if self.artifact_dir is not None else None,
        }
        if self.error_class:
            payload["error"] = {"class": self.error_class, "message": self.error_message or ""}
        return safe_data(payload)


class MockProviderDecisionAdapter(LLMDecisionAdapter):
    """Deterministic provider-labeled adapter for Web tests/dev only."""

    prompt_version = "mock-provider-v1"

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        topic_overlap = len(set(post.topic_tags) & set(profile.interest_tags))
        probability = round(min(0.55 + 0.1 * topic_overlap + 0.1 * peer_context.engagement_ratio, 0.95), 4)
        action: EngagementAction = "share" if probability >= 0.75 else "like"
        return EngageDecision(
            engage=True,
            probability=probability,
            reason="mock provider decision for local Web test/dev mode",
            confidence=0.9,
            action=action,
            decision_source="provider",
            provider_metadata={
                "provider": "mock",
                "model": "mock-web-provider",
                "wire_api": "mock",
                "adapter": "mock_web_provider",
                "adapter_version": "web-mvp-v1",
                "prompt_version": self.prompt_version,
            },
        )


class WebRunStore:
    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.datasets: dict[str, DatasetUpload] = {}
        self.jobs: dict[str, RunJob] = {}

    def add_dataset(self, upload: DatasetUpload) -> None:
        self.datasets[upload.validation_id] = upload

    def provider_readiness(self, *, mock_provider: bool = False) -> dict[str, Any]:
        if mock_provider:
            return {
                "state": "mock",
                "ready": True,
                "mock": True,
                "label": "Mock provider mode / 模拟 Provider 模式",
                "provider": {"provider": "mock", "model": "mock-web-provider"},
                "reasons": [],
            }

        config = _product_provider_config()
        reasons: list[str] = []
        sdk_available = _openai_sdk_available()
        live_gate = os.environ.get("LLM_ABM_RUN_LIVE_LLM") == "1"
        codex_provider = load_codex_provider_config() if config.use_codex_provider_config else None
        credential = resolve_runtime_credential(
            api_key_env=config.api_key_env,
            codex_provider=codex_provider,
        )
        if not sdk_available:
            reasons.append("optional openai dependency is not installed")
        if not live_gate:
            reasons.append("LLM_ABM_RUN_LIVE_LLM=1 live gate is not enabled")
        if codex_provider is None and config.use_codex_provider_config and not os.environ.get(config.api_key_env):
            reasons.append("Codex provider metadata or API key environment is not available")
        if credential is None:
            reasons.append(f"runtime credential is missing from Codex auth or {config.api_key_env}")
        state = "ready" if not reasons else "blocked"
        return safe_data(
            {
                "state": state,
                "ready": state == "ready",
                "mock": False,
                "provider": config.safe_metadata(),
                "codex_provider": codex_provider.redacted() if codex_provider is not None else None,
                "checks": {
                    "openai_sdk_available": sdk_available,
                    "live_gate_enabled": live_gate,
                    "credential_available": credential is not None,
                },
                "reasons": reasons,
            }
        )

    def create_run(self, payload: dict[str, Any]) -> RunJob:
        mock_provider = bool(payload.get("mock_provider", False))
        run_id = _safe_run_id(str(payload.get("run_id") or f"web-run-{uuid4().hex[:10]}"))
        job = RunJob(run_id=run_id, mode="mock" if mock_provider else "product")
        self.jobs[run_id] = job

        readiness = self.provider_readiness(mock_provider=mock_provider)
        if readiness["state"] == "blocked":
            self._mark_blocked(job, "ProviderReadinessBlocked", "; ".join(readiness.get("reasons", [])))
            return job

        thread = threading.Thread(
            target=self._run_job_thread,
            args=(job, payload),
            kwargs={"mock_provider": mock_provider, "provider_readiness": readiness},
            name=f"llm-abm-web-run-{run_id}",
            daemon=True,
        )
        thread.start()
        return job

    def _run_job_thread(
        self,
        job: RunJob,
        payload: dict[str, Any],
        *,
        mock_provider: bool,
        provider_readiness: dict[str, Any],
    ) -> None:
        try:
            self._run_now(job, payload, mock_provider=mock_provider, provider_readiness=provider_readiness)
        except Exception as exc:  # noqa: BLE001 - local Web API returns safe structured failures.
            self._mark_failed(job, exc.__class__.__name__, _safe_error_message(exc))

    def get_job(self, run_id: str) -> RunJob | None:
        return self.jobs.get(run_id)

    def report_payload(self, run_id: str) -> dict[str, Any]:
        job = self._require_job(run_id)
        if job.artifact_dir is None or not (job.artifact_dir / "report_payload.json").exists():
            raise FileNotFoundError("report payload is not available for this run")
        return safe_data(json.loads((job.artifact_dir / "report_payload.json").read_text(encoding="utf-8")))

    def artifact_path(self, run_id: str, name: str) -> Path:
        if name not in ARTIFACT_ALLOWLIST:
            raise FileNotFoundError("artifact is not allowlisted")
        job = self._require_job(run_id)
        if job.artifact_dir is None:
            raise FileNotFoundError("run has no artifact directory")
        path = (job.artifact_dir / name).resolve()
        root = job.artifact_dir.resolve()
        if root not in path.parents and path != root:
            raise FileNotFoundError("artifact path escaped run directory")
        if not path.exists():
            raise FileNotFoundError("artifact does not exist")
        return path

    def _run_now(
        self,
        job: RunJob,
        payload: dict[str, Any],
        *,
        mock_provider: bool,
        provider_readiness: dict[str, Any],
    ) -> None:
        job.state = "running"
        job.updated_at = _utcnow()
        job.progress_label = "running simulation"
        dataset = self._dataset_for_payload(payload)
        config = _build_simulation_input(payload, dataset, mock_provider=mock_provider, run_id=job.run_id)
        adapter = MockProviderDecisionAdapter() if mock_provider else None
        output_dir = self.artifact_root / job.run_id
        runner = ExperimentRunner(config, decision_adapter=adapter)
        output_path = runner.run_and_write(output_dir)
        result = json.loads((output_path / "run_result.json").read_text(encoding="utf-8"))
        source_summary = decision_source_summary_json(result)
        if source_summary.get("provider", 0) <= 0:
            raise ProviderConfigurationError("Web product run produced zero provider-backed decisions")
        if dataset is not None and runner.dataset_validation_report is not None:
            (output_path / "dataset_validation.json").write_text(
                json.dumps(
                    safe_dataset_validation_report(runner.dataset_validation_report), ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
        self._write_web_metadata(output_path, provider_readiness, mock_provider=mock_provider)
        job.artifact_dir = output_path
        job.state = "succeeded"
        job.progress_label = "succeeded"
        job.updated_at = _utcnow()

    def _dataset_for_payload(self, payload: dict[str, Any]) -> DatasetUpload | None:
        validation_id = payload.get("validation_id")
        if not validation_id:
            raise ValueError("validation_id is required; validate uploads before running")
        dataset = self.datasets.get(str(validation_id))
        if dataset is None:
            raise ValueError(f"unknown validation_id: {validation_id}")
        return dataset

    def _write_web_metadata(
        self, output_path: Path, provider_readiness: dict[str, Any], *, mock_provider: bool
    ) -> None:
        metadata = {
            "web_console": True,
            "mode": "mock" if mock_provider else "product",
            "mock_provider": mock_provider,
            "provider_readiness": provider_readiness,
        }
        (output_path / "web_run_metadata.json").write_text(
            json.dumps(safe_data(metadata), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _mark_blocked(self, job: RunJob, error_class: str, message: str) -> None:
        job.state = "blocked"
        job.error_class = error_class
        job.error_message = message
        job.progress_label = "blocked by provider readiness"
        job.updated_at = _utcnow()

    def _mark_failed(self, job: RunJob, error_class: str, message: str) -> None:
        job.state = "failed"
        job.error_class = error_class
        job.error_message = message
        job.progress_label = "failed"
        job.updated_at = _utcnow()

    def _require_job(self, run_id: str) -> RunJob:
        job = self.jobs.get(run_id)
        if job is None:
            raise FileNotFoundError("run not found")
        return job


def _build_simulation_input(
    payload: dict[str, Any],
    dataset: DatasetUpload | None,
    *,
    mock_provider: bool,
    run_id: str,
) -> SimulationInput:
    raw_scenario = payload.get("scenario")
    scenario = cast(dict[str, Any], raw_scenario if isinstance(raw_scenario, dict) else payload)
    seed_user_ids = _string_list(scenario.get("seed_user_ids") or scenario.get("seedUsers"))
    horizon = int(scenario.get("horizon", 4))
    language = _language(str(scenario.get("report_language") or scenario.get("language") or "en-US"))
    post = PostContent(
        post_id=str(scenario.get("post_id") or "web-post"),
        text=str(scenario.get("post_text") or scenario.get("text") or "Local Web console campaign post"),
        topic_tags=_string_list(scenario.get("topic_tags") or scenario.get("topics")),
        media_summary=(str(scenario.get("media_summary")) if scenario.get("media_summary") else None),
    )
    platform = PlatformContext(
        time_label=str(scenario.get("time_label") or "local web run"),
        hot_topics=_string_list(scenario.get("hot_topics")),
        platform_mood=str(scenario.get("platform_mood") or "launch"),
        feed_ranking_weight=float(scenario.get("feed_ranking_weight", 1.0)),
    )
    provider_config = _product_provider_config().model_copy(
        update={"provider": "mock", "model": "mock-web-provider", "require_live_env": False} if mock_provider else {}
    )
    return SimulationInput(
        run_id=run_id,
        random_seed=int(scenario.get("random_seed", 42)),
        simulation=SimulationConfig(horizon=horizon, seed_user_ids=seed_user_ids),
        platform_context=platform,
        post=post,
        dataset=dataset.dataset_config if dataset is not None else None,  # type: ignore[arg-type]
        report=ReportConfig(
            title=str(scenario.get("report_title") or "LLM-ABM Local Web Console Report"),
            default_language=language,
        ),
        provider_llm=provider_config,
    )


def _product_provider_config() -> ProviderLLMConfig:
    return ProviderLLMConfig(
        enabled=True,
        provider="openai_compatible",
        use_codex_provider_config=True,
        require_live_env=True,
        fail_closed_action=FailClosedAction.RAISE,
        prompt_version="engage-provider-web-v1",
    )


def _openai_sdk_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("openai") is not None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).replace(";", ",").split(",") if part.strip()]


def _language(value: str) -> SupportedLanguage:
    return "zh-CN" if value == "zh-CN" else "en-US"


def _safe_run_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in value).strip("-")
    return safe or f"web-run-{uuid4().hex[:10]}"


def _safe_error_message(exc: Exception) -> str:
    message = str(exc)
    for fragment in ("sk-", "Bearer", "authorization", "cookie", "access_token"):
        message = message.replace(fragment, "<redacted>")
    return message[:800]


def decision_source_summary_json(result_payload: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for step in result_payload.get("step_records", []):
        for event in step.get("decision_events", []):
            source = event.get("decision", {}).get("decision_source", "unknown")
            counts[source] = counts.get(source, 0) + 1
    return counts
