from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

from .agent import SocialUserAgent
from .decision import CachedDecisionAdapter, InMemoryDecisionCache, RuleBasedDecisionAdapter
from .environment import PlatformEnvironment
from .events import SimulationRunResult
from .graph_loader import load_edge_list
from .metrics import MetricsCollector
from .model import SimulationModel
from .outputs import copy_config_source, write_run_outputs
from .schemas import SimulationInput, UserProfile


class ExperimentRunner:
    """Build and run a reproducible simulation from a config file."""

    def __init__(self, config: SimulationInput) -> None:
        self.config = config

    @classmethod
    def from_config_file(cls, path: str | Path) -> ExperimentRunner:
        return cls(load_simulation_input(path))

    def run(self) -> SimulationRunResult:
        graph = self._build_graph()
        profiles = self._build_profiles(graph)
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
            decision_adapter=CachedDecisionAdapter(RuleBasedDecisionAdapter(), InMemoryDecisionCache()),
            metrics=MetricsCollector(),
            platform_context=self.config.platform_context,
            run_id=self.config.run_id,
            random_seed=self.config.random_seed,
        )
        return model.run(self.config.simulation.horizon)

    def run_and_write(self, output_dir: str | Path, config_path: str | Path | None = None) -> Path:
        result = self.run()
        output_path = write_run_outputs(result, self.config, output_dir)
        if config_path is not None:
            copy_config_source(config_path, output_path)
        return output_path

    def _build_graph(self) -> nx.Graph:
        if self.config.dataset.edge_list_path:
            return load_edge_list(self.config.dataset.edge_list_path, delimiter=self.config.dataset.delimiter)
        graph = nx.Graph()
        graph.add_edges_from((str(left), str(right)) for left, right in self.config.graph_edges)
        for profile in self.config.profiles:
            graph.add_node(profile.user_id)
        return graph

    def _build_profiles(self, graph: nx.Graph) -> dict[str, UserProfile]:
        profiles = {profile.user_id: profile for profile in self.config.profiles}
        for node in sorted(str(node) for node in graph.nodes):
            profiles.setdefault(node, UserProfile(user_id=node))
        return profiles


def load_simulation_input(path: str | Path) -> SimulationInput:
    config_path = Path(path)
    raw = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        data: dict[str, Any] = json.loads(raw)
    else:
        loaded = yaml.safe_load(raw)
        data = loaded or {}
    return _normalize_legacy_config(data)


def _normalize_legacy_config(data: dict[str, Any]) -> SimulationInput:
    """Support the original flat default.yaml while preferring the new nested schema."""

    if "simulation" in data:
        return SimulationInput.model_validate(data)

    simulation_keys = {
        "horizon",
        "seed_user_ids",
        "base_exposure_probability",
        "peer_exposure_boost",
    }
    simulation = {key: data.pop(key) for key in list(data) if key in simulation_keys}
    if simulation:
        data["simulation"] = simulation
    return SimulationInput.model_validate(data)
