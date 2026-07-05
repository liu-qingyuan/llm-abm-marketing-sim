from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .agent import SocialUserAgent
from .decision import CachedDecisionAdapter, InMemoryDecisionCache, LLMDecisionAdapter, RuleBasedDecisionAdapter
from .environment import PlatformEnvironment
from .events import SimulationRunResult
from .graph_loader import DatasetValidationReport, load_network_dataset
from .metrics import MetricsCollector
from .model import SimulationModel
from .outputs import copy_config_source, write_run_outputs
from .provider_config import load_codex_provider_config
from .schemas import FailClosedAction, SimulationInput

DATASET_PATH_FIELDS = ("edge_list_path", "profile_path")


class ExperimentRunner:
    """Build and run a reproducible simulation from a config file."""

    def __init__(self, config: SimulationInput, decision_adapter: LLMDecisionAdapter | None = None) -> None:
        self.config = config
        self.decision_adapter_override = decision_adapter
        self.dataset_validation_report: DatasetValidationReport | None = None

    @classmethod
    def from_config_file(cls, path: str | Path) -> ExperimentRunner:
        return cls(load_simulation_input(path))

    def run(self) -> SimulationRunResult:
        dataset = self._build_dataset()
        graph = dataset.graph
        profiles = dataset.profiles
        self.dataset_validation_report = dataset.validation_report
        agents = {user_id: SocialUserAgent(profile=profile) for user_id, profile in sorted(profiles.items())}
        environment = PlatformEnvironment(
            graph=graph,
            config=self.config.simulation,
            rng=random.Random(self.config.random_seed),
            platform_context=self.config.platform_context,
            post=self.config.post,
        )
        model = SimulationModel(
            post=self.config.post,
            agents=agents,
            environment=environment,
            decision_adapter=self._build_decision_adapter(),
            metrics=MetricsCollector(),
            platform_context=self.config.platform_context,
            run_id=self.config.run_id,
            random_seed=self.config.random_seed,
        )
        return model.run(self.config.simulation.horizon)

    def run_and_write(self, output_dir: str | Path, config_path: str | Path | None = None) -> Path:
        result = self.run()
        output_path = write_run_outputs(
            result,
            self.config,
            output_dir,
            self.dataset_validation_report,
            provider_readiness=self._provider_readiness_metadata(),
        )
        if config_path is not None:
            copy_config_source(config_path, output_path)
        return output_path

    def _build_decision_adapter(self) -> LLMDecisionAdapter:
        if self.decision_adapter_override is not None:
            return self.decision_adapter_override
        provider_config = self.config.provider_llm
        if not provider_config.enabled:
            return CachedDecisionAdapter(
                RuleBasedDecisionAdapter(self.config.rule_based_decision),
                InMemoryDecisionCache(),
            )
        if provider_config.fail_closed_action == FailClosedAction.SKIP_RUN:
            raise RuntimeError("provider_llm.fail_closed_action=skip_run prevents simulator run start")
        from .providers.openai_compatible import OpenAICompatibleDecisionAdapter

        return CachedDecisionAdapter(
            OpenAICompatibleDecisionAdapter(provider_config),
            InMemoryDecisionCache(),
            prompt_version=provider_config.prompt_version,
        )

    def _provider_readiness_metadata(self) -> dict[str, Any] | None:
        if not self.config.provider_llm.enabled:
            return None
        metadata: dict[str, Any] = {"configured": self.config.provider_llm.safe_metadata()}
        if self.config.provider_llm.use_codex_provider_config:
            codex_config = load_codex_provider_config()
            metadata["codex_provider"] = codex_config.redacted() if codex_config is not None else None
        else:
            metadata["codex_provider"] = None
        return metadata

    def _build_dataset(self):
        return load_network_dataset(
            self.config.dataset,
            inline_edges=[(str(left), str(right)) for left, right in self.config.graph_edges],
            inline_profiles=self.config.profiles,
            seed_user_ids=self.config.simulation.seed_user_ids,
        )


def load_simulation_input(path: str | Path) -> SimulationInput:
    config_path = Path(path)
    raw = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        data: dict[str, Any] = json.loads(raw)
    else:
        loaded = yaml.safe_load(raw)
        data = loaded or {}
    return _normalize_legacy_config(data, config_path.parent)


def _normalize_legacy_config(data: dict[str, Any], config_dir: Path | None = None) -> SimulationInput:
    """Support the original flat default.yaml while preferring the new nested schema."""

    if "simulation" in data:
        return _resolve_dataset_paths(SimulationInput.model_validate(data), config_dir)

    simulation_keys = {
        "horizon",
        "seed_user_ids",
        "base_exposure_probability",
        "peer_exposure_boost",
    }
    simulation = {key: data.pop(key) for key in list(data) if key in simulation_keys}
    if simulation:
        data["simulation"] = simulation
    return _resolve_dataset_paths(SimulationInput.model_validate(data), config_dir)


def _resolve_dataset_paths(config: SimulationInput, config_dir: Path | None) -> SimulationInput:
    """Resolve dataset file paths relative to the source config directory.

    Absolute paths are normalized in place. When no config directory is known,
    paths stay as authored so direct model validation remains side-effect free.
    """

    if config_dir is None:
        return config

    config_dir = config_dir.resolve()
    dataset = config.dataset
    updates: dict[str, Path] = {}
    for field_name in DATASET_PATH_FIELDS:
        raw_path = getattr(dataset, field_name)
        if raw_path is None:
            continue
        updates[field_name] = raw_path.resolve() if raw_path.is_absolute() else (config_dir / raw_path).resolve()

    if not updates:
        return config
    return config.model_copy(update={"dataset": dataset.model_copy(update=updates)})
