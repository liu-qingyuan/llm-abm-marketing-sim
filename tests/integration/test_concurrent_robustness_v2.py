from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from llm_abm_sim import (
    ConcurrentRobustnessManifestV2,
    ConcurrentRobustnessStudy,
    ConcurrentRobustnessStudyStatus,
    EngageDecision,
    LLMDecisionAdapter,
    ProviderDecisionError,
)
from llm_abm_sim import concurrent_robustness_v2 as v2_module
from llm_abm_sim.concurrent_robustness_v2 import (
    _V2_MODELS,
    _V2_REQUIRED_OBSERVED_MODELS,
    _derive_v2_realization_source_contract,
    _realization_source_payload,
)
from llm_abm_sim.decision import EngagementAction, ProviderResponseProvenanceUnknown
from llm_abm_sim.prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from tests.integration.test_concurrent_message_experiment_runner import (
    _make_validation_report_source,
    _robustness_manifest_for_source,
)


def _v2_manifest_payload(source_dir: Path, *, output_identity: str) -> dict[str, object]:
    v1 = _robustness_manifest_for_source(source_dir, output_identity=f"{output_identity}-v1-source")
    v1_payload = v1.model_dump(mode="json")
    cells = [
        {
            "cell_id": f"{prompt.variant_id}::{model}",
            "prompt_variant": prompt.variant_id,
            "prompt_version": prompt.prompt_version,
            "prompt_canonical_hash": prompt.canonical_hash,
            "requested_model": model,
            "required_observed_model": _V2_REQUIRED_OBSERVED_MODELS[model],
        }
        for prompt in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
        for model in _V2_MODELS
    ]
    ranking = copy.deepcopy(v1_payload["ranking_contract"])
    logical_per_cell = int(ranking["horizon"]) * int(ranking["delivery_capacity"]) * 3
    return {
        "schema_version": "concurrent-robustness-manifest-v2",
        "source": copy.deepcopy(v1_payload["source"]),
        "sample": copy.deepcopy(v1_payload["sample"]),
        "message_ids": copy.deepcopy(v1_payload["message_ids"]),
        "message_snapshot_sha256": v1_payload["message_snapshot_sha256"],
        "ranking_contract": ranking,
        "prompt_model_cells": cells,
        "request_contract": copy.deepcopy(v1_payload["request_contract"]),
        "request_caps": {
            "logical_judgments_per_cell": logical_per_cell,
            "logical_judgment_cap": logical_per_cell * 20,
            "physical_attempt_cap": logical_per_cell * 20 * 3,
            "maximum_physical_attempts_per_judgment": 3,
        },
        "formal_contract": {
            "schema_version": "concurrent-robustness-formal-topology-v2",
            "model_count": 5,
            "prompt_variants": ["P0", "P1", "P2", "P3"],
            "cell_count": 20,
            "sample_size": 1_000,
            "batch_count": 30,
            "message_count": 3,
            "delivery_capacity_per_message": 20,
            "logical_judgments_per_cell": 1_800,
            "logical_judgment_cap": 36_000,
            "maximum_physical_attempts_per_judgment": 3,
            "physical_attempt_cap": 108_000,
        },
        "batch_barrier": {
            "schema_version": "concurrent-robustness-two-stage-barrier-v2",
            "required_terminal": "persisted-realized-terminal-per-selected-pair-v1",
            "feedback_source": "campaign-deduplicated-realized-positive-users-v1",
            "feedback_timing": "next-batch-only-v1",
        },
        "realization_source": _derive_v2_realization_source_contract(source_dir),
        "execution_profile": "deterministic_validation",
        "authorization_reference": f"deterministic-validation:{output_identity}",
        "output_identity": output_identity,
    }


def _v2_manifest(source_dir: Path, *, output_identity: str) -> ConcurrentRobustnessManifestV2:
    return ConcurrentRobustnessManifestV2.model_validate(
        _v2_manifest_payload(source_dir, output_identity=output_identity)
    )


def test_v2_schema_dispatch_rejects_untyped_lookalike(tmp_path: Path) -> None:
    class _V2Lookalike(BaseModel):
        schema_version: str = v2_module.CONCURRENT_ROBUSTNESS_MANIFEST_V2_SCHEMA

    with pytest.raises(v2_module.ConcurrentRobustnessError) as captured:
        ConcurrentRobustnessStudy().run(
            _V2Lookalike(),
            adapters_by_cell=None,
            output_dir=tmp_path / "untyped-v2",
        )

    assert captured.value.code == v2_module.ConcurrentRobustnessErrorCode.INVALID_MANIFEST
    assert not (tmp_path / "untyped-v2").exists()


def test_v2_manifest_freezes_exact_twenty_cell_topology_and_caps(tmp_path: Path) -> None:
    source = _make_validation_report_source(tmp_path, "v2-manifest-source")
    manifest = _v2_manifest(source, output_identity="v2-manifest-validation")

    assert manifest.schema_version == "concurrent-robustness-manifest-v2"
    assert tuple(cell.cell_id for cell in manifest.prompt_model_cells) == tuple(
        f"{prompt.variant_id}::{model}"
        for prompt in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
        for model in _V2_MODELS
    )
    assert len(manifest.prompt_model_cells) == 20
    assert manifest.request_caps.logical_judgments_per_cell == 60
    assert manifest.request_caps.logical_judgment_cap == 1_200
    assert manifest.request_caps.physical_attempt_cap == 3_600
    assert manifest.formal_contract.logical_judgment_cap == 36_000
    assert manifest.formal_contract.physical_attempt_cap == 108_000
    assert manifest.realization_source.sample_identity == manifest.sample.sample_identity
    assert manifest.realization_source.message_ids == manifest.message_ids
    assert manifest.realization_source.message_snapshot_sha256 == manifest.message_snapshot_sha256
    assert set(manifest.realization_source.model_dump()) == {
        "schema_version",
        "sample_identity",
        "graph_identity_sha256",
        "message_ids",
        "message_snapshot_sha256",
        "realization_rule_version",
        "realization_seed",
        "canonical_facts_sha256",
        "source_identity",
    }


@pytest.mark.parametrize("corruption", ["missing", "extra", "reordered", "crossed_prompt", "crossed_model"])
def test_v2_manifest_rejects_noncanonical_or_crossed_cells(tmp_path: Path, corruption: str) -> None:
    source = _make_validation_report_source(tmp_path, f"v2-manifest-{corruption}-source")
    payload = _v2_manifest_payload(source, output_identity=f"v2-manifest-{corruption}")
    cells = payload["prompt_model_cells"]
    assert isinstance(cells, list)
    if corruption == "missing":
        cells.pop()
    elif corruption == "extra":
        cells.append(copy.deepcopy(cells[-1]))
        cells[-1]["cell_id"] = "P3::extra-model"
        cells[-1]["requested_model"] = "extra-model"
        cells[-1]["required_observed_model"] = "extra-model"
    elif corruption == "reordered":
        cells[0], cells[1] = cells[1], cells[0]
    elif corruption == "crossed_prompt":
        cells[0]["prompt_canonical_hash"] = "sha256:" + "0" * 64
    else:
        cells[0]["required_observed_model"] = "crossed-observed-model"

    with pytest.raises(ValueError, match="20 canonical Prompt-Model cells"):
        ConcurrentRobustnessManifestV2.model_validate(payload)


def test_v2_manifest_rejects_crossed_realization_facts_and_formal_shortcuts(tmp_path: Path) -> None:
    source = _make_validation_report_source(tmp_path, "v2-manifest-crossed-realization-source")
    payload = _v2_manifest_payload(source, output_identity="v2-manifest-crossed-realization")

    crossed = copy.deepcopy(payload)
    crossed_realization = crossed["realization_source"]
    assert isinstance(crossed_realization, dict)
    crossed_realization["message_snapshot_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="realization source"):
        ConcurrentRobustnessManifestV2.model_validate(crossed)

    formal_shortcut = copy.deepcopy(payload)
    formal_source = formal_shortcut["source"]
    assert isinstance(formal_source, dict)
    formal_source["kind"] = "formal"
    formal_shortcut["execution_profile"] = "formal"
    with pytest.raises(ValueError, match="Formal v2 profile"):
        ConcurrentRobustnessManifestV2.model_validate(formal_shortcut)


def test_v2_runtime_rejects_crossed_effective_graph_before_adapter_calls(tmp_path: Path) -> None:
    source = _make_validation_report_source(tmp_path, "v2-crossed-graph-source")
    payload = _v2_manifest_payload(source, output_identity="v2-crossed-graph")
    realization = payload["realization_source"]
    assert isinstance(realization, dict)
    payload["realization_source"] = _realization_source_payload(
        sample_identity=str(realization["sample_identity"]),
        graph_identity_sha256="0" * 64,
        message_ids=tuple(realization["message_ids"]),
        message_snapshot_sha256=str(realization["message_snapshot_sha256"]),
    )
    manifest = ConcurrentRobustnessManifestV2.model_validate(payload)
    adapters, typed_adapters = _v2_adapters(manifest)
    workspace = tmp_path / "v2-crossed-graph-workspace"

    with pytest.raises(v2_module.ConcurrentRobustnessError) as captured:
        ConcurrentRobustnessStudy().run(manifest, adapters, workspace)

    assert captured.value.code == v2_module.ConcurrentRobustnessErrorCode.INVALID_SOURCE
    assert all(adapter.calls == [] for adapter in typed_adapters.values())
    assert not workspace.exists()


class _DeterministicPanelAdapter(LLMDecisionAdapter):
    deterministic_validation = True
    external_request_invocations = 0
    live_api_triggered = False

    def __init__(self, *, prompt_version: str, observed_model: str, cell_index: int) -> None:
        self.prompt_version = prompt_version
        self.observed_model = observed_model
        self.cell_index = cell_index
        self.request_invocations = 0
        self.calls: list[tuple[str, str, int]] = []

    def decide(
        self,
        post: Any,
        profile: Any,
        peer_context: Any,
        platform_context: Any = None,
        time_step: int = 0,
    ) -> EngageDecision:
        del peer_context, platform_context
        self.request_invocations += 1
        self.calls.append((profile.user_id, post.post_id, time_step))
        stable_value = sum(f"{profile.user_id}:{post.post_id}".encode())
        engage = stable_value % 4 != 0
        action_by_message: dict[str, EngagementAction] = {
            "message_1": "like",
            "message_2": "comment",
            "message_3": "share",
        }
        return EngageDecision(
            engage=engage,
            probability=0.61 if engage else 0.17,
            reason="deterministic v2 Judgment",
            confidence=0.88,
            action=action_by_message[post.post_id] if engage else "ignore",
            decision_source="deterministic_v2_fixture",
            provider_metadata={"model": self.observed_model},
        )


def _v2_adapters(
    manifest: ConcurrentRobustnessManifestV2,
    *,
    reverse_insertion_order: bool = False,
) -> tuple[dict[str, LLMDecisionAdapter], dict[str, _DeterministicPanelAdapter]]:
    rows = list(enumerate(manifest.prompt_model_cells))
    if reverse_insertion_order:
        rows.reverse()
    typed: dict[str, _DeterministicPanelAdapter] = {}
    for cell_index, cell in rows:
        assert cell.required_observed_model is not None
        typed[cell.cell_id] = _DeterministicPanelAdapter(
            prompt_version=cell.prompt_version,
            observed_model=cell.required_observed_model,
            cell_index=cell_index,
        )
    return dict(typed), typed


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_v2_study_runs_twenty_two_stage_cells_and_replays_without_calls(tmp_path: Path) -> None:
    source = _make_validation_report_source(tmp_path, "v2-study-source")
    manifest = _v2_manifest(source, output_identity="v2-study-validation")
    adapters, typed_adapters = _v2_adapters(manifest, reverse_insertion_order=True)
    workspace = tmp_path / "v2-study-workspace"

    result = ConcurrentRobustnessStudy().run(manifest, adapters, workspace)

    assert result.status == ConcurrentRobustnessStudyStatus.CELLS_COMPLETE
    assert result.workspace_root == workspace.resolve()
    assert result.study_root is None
    assert result.report_candidate is None
    assert result.logical_provider_attempts == 1_200
    assert result.physical_provider_attempts == 1_200
    assert all(len(adapter.calls) == 60 for adapter in typed_adapters.values())
    assert all(adapter.external_request_invocations == 0 for adapter in typed_adapters.values())
    execution = workspace / "two_stage_execution"
    assert {path.name for path in execution.iterdir()} == {
        "execution_manifest.json",
        "execution_anchor.json",
        "cell_registry.json",
        "terminal_rows.jsonl",
        "batch_commits.jsonl",
        "pair_lifecycle.jsonl",
    }

    execution_manifest = json.loads((execution / "execution_manifest.json").read_text(encoding="utf-8"))
    terminals = _jsonl(execution / "terminal_rows.jsonl")
    commits = _jsonl(execution / "batch_commits.jsonl")
    lifecycle = _jsonl(execution / "pair_lifecycle.jsonl")
    assert execution_manifest["schema_version"] == "concurrent-robustness-two-stage-execution-v2"
    assert execution_manifest["counts"] == {
        "cells": 20,
        "logical_judgments": 1_200,
        "physical_attempts": 1_200,
        "realized_terminals": 1_200,
        "batch_commits": 40,
    }
    assert execution_manifest["provider_calls"] == 0
    assert execution_manifest["live_api_triggered"] is False
    assert execution_manifest["production_deploy_eligible"] is False
    assert len(terminals) == 1_200
    assert len(commits) == 40
    assert len(lifecycle) == 1_200 * 6
    assert not any("realized_reason" in terminal for terminal in terminals)

    first_pair_rows = [
        row
        for row in terminals
        if row["user_id"] == terminals[0]["user_id"] and row["message_id"] == terminals[0]["message_id"]
    ]
    assert len(first_pair_rows) == 20
    assert len({row["judgment_source_identity"] for row in first_pair_rows}) == 20
    assert {row["realization_source_identity"] for row in first_pair_rows} == {
        manifest.realization_source.source_identity
    }
    assert len({row["realization_key"] for row in first_pair_rows}) == 1
    assert len({row["uniform_draw"] for row in first_pair_rows}) == 1
    provider_ignore = next(row for row in terminals if row["realization_status"] == "provider_ignore")
    assert provider_ignore["uniform_draw"] is None
    assert provider_ignore["realized_action"] == "ignore"

    first_cell_first_pair = lifecycle[0]["pair_id"]
    assert [
        row["state"]
        for row in lifecycle
        if row["cell_id"] == lifecycle[0]["cell_id"] and row["pair_id"] == first_cell_first_pair
    ] == [
        "pending",
        "reserved",
        "attempting",
        "judgment_persisted",
        "realized_persisted",
        "settled",
    ]
    first_cell_commits = [row for row in commits if row["cell_index"] == 0]
    assert (
        first_cell_commits[1]["frozen_campaign_engaged_user_ids"]
        == first_cell_commits[0]["committed_realized_positive_user_ids"]
    )

    before = _snapshot(workspace)
    replay_adapters, replay_typed = _v2_adapters(manifest)
    replayed = ConcurrentRobustnessStudy().run(manifest, replay_adapters, workspace)
    assert replayed == result
    assert all(adapter.calls == [] for adapter in replay_typed.values())
    assert _snapshot(workspace) == before


@pytest.mark.parametrize("interrupted_state", ["judgment_persisted", "realized_persisted"])
def test_v2_resume_continues_persisted_stage_without_repeating_provider_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupted_state: str,
) -> None:
    source = _make_validation_report_source(tmp_path, f"v2-resume-{interrupted_state}-source")
    manifest = _v2_manifest(source, output_identity=f"v2-resume-{interrupted_state}")
    adapters, typed_adapters = _v2_adapters(manifest)
    workspace = tmp_path / f"v2-resume-{interrupted_state}-workspace"
    original_append = v2_module._V2PairLedger.append_state
    interrupted = False

    def append_then_interrupt(
        ledger: Any,
        plan: Any,
        state: str,
        *,
        payload: Any = None,
    ) -> None:
        nonlocal interrupted
        original_append(ledger, plan, state, payload=payload)
        if state == interrupted_state and not interrupted:
            interrupted = True
            raise RuntimeError(f"injected interruption after {state}")

    monkeypatch.setattr(v2_module._V2PairLedger, "append_state", append_then_interrupt)
    with pytest.raises(RuntimeError, match="injected interruption"):
        ConcurrentRobustnessStudy().run(manifest, adapters, workspace)
    first_cell_id = manifest.prompt_model_cells[0].cell_id
    assert len(typed_adapters[first_cell_id].calls) == 1
    assert all(adapter.calls == [] for cell_id, adapter in typed_adapters.items() if cell_id != first_cell_id)
    assert not (workspace / "two_stage_execution").exists()

    monkeypatch.setattr(v2_module._V2PairLedger, "append_state", original_append)
    resume_adapters, resume_typed = _v2_adapters(manifest)
    result = ConcurrentRobustnessStudy().run(manifest, resume_adapters, workspace)

    assert result.status == ConcurrentRobustnessStudyStatus.CELLS_COMPLETE
    assert len(resume_typed[first_cell_id].calls) == 59
    assert all(len(adapter.calls) == 60 for cell_id, adapter in resume_typed.items() if cell_id != first_cell_id)
    lifecycle = _jsonl(workspace / "two_stage_execution" / "pair_lifecycle.jsonl")
    first_pair_id = lifecycle[0]["pair_id"]
    assert [row["state"] for row in lifecycle if row["cell_index"] == 0 and row["pair_id"] == first_pair_id] == [
        "pending",
        "reserved",
        "attempting",
        "judgment_persisted",
        "realized_persisted",
        "settled",
    ]


def test_v2_provider_failure_stops_before_batch_commit_without_fabricating_ignore(
    tmp_path: Path,
) -> None:
    source = _make_validation_report_source(tmp_path, "v2-provider-failure-source")
    manifest = _v2_manifest(source, output_identity="v2-provider-failure")
    adapters, typed_adapters = _v2_adapters(manifest)
    first_cell_id = manifest.prompt_model_cells[0].cell_id
    failing = typed_adapters[first_cell_id]

    def fail_decision(*args: Any, **kwargs: Any) -> EngageDecision:
        del args, kwargs
        failing.request_invocations += 1
        failing.calls.append(("failed", "failed", 0))
        raise ProviderDecisionError(TimeoutError("deterministic failure"))

    failing.decide = fail_decision  # type: ignore[method-assign]
    workspace = tmp_path / "v2-provider-failure-workspace"

    result = ConcurrentRobustnessStudy().run(manifest, adapters, workspace)

    assert result.status == ConcurrentRobustnessStudyStatus.STOPPED
    assert result.study_root is None
    assert result.report_candidate is None
    assert result.logical_provider_attempts == 1
    assert result.physical_provider_attempts == 1
    assert len(failing.calls) == 1
    assert all(adapter.calls == [] for cell_id, adapter in typed_adapters.items() if cell_id != first_cell_id)
    assert not (workspace / "two_stage_execution").exists()
    operational = tmp_path / f".{workspace.name}.two-stage-v2-operational"
    ledger = _jsonl(operational / "cell-00" / "pair_lifecycle.jsonl")
    assert [row["state"] for row in ledger] == [
        "pending",
        "reserved",
        "attempting",
        "stopped",
    ]
    failure_payload = ledger[-1]["payload"]
    assert isinstance(failure_payload, dict)
    assert failure_payload["terminal_status"] == "provider_failed"
    assert all(row["state"] != "realized_persisted" for row in ledger)
    runtime_journal = operational / "cell-00" / ".runtime.operational" / "concurrent_message_execution_journal.jsonl"
    runtime_events = _jsonl(runtime_journal)
    assert all(row.get("event_type") != "batch_committed" for row in runtime_events)

    resume_adapters, resume_typed = _v2_adapters(manifest)
    resumed = ConcurrentRobustnessStudy().run(manifest, resume_adapters, workspace)
    assert resumed == result
    assert all(adapter.calls == [] for adapter in resume_typed.values())


def test_v2_unknown_dispatched_attempt_requires_reconciliation_without_replay(
    tmp_path: Path,
) -> None:
    source = _make_validation_report_source(tmp_path, "v2-unknown-attempt-source")
    manifest = _v2_manifest(source, output_identity="v2-unknown-attempt")
    adapters, typed_adapters = _v2_adapters(manifest)
    first_cell_id = manifest.prompt_model_cells[0].cell_id
    unknown = typed_adapters[first_cell_id]

    def lose_provenance(*args: Any, **kwargs: Any) -> EngageDecision:
        del args, kwargs
        unknown.request_invocations += 1
        unknown.calls.append(("unknown", "unknown", 0))
        raise ProviderResponseProvenanceUnknown("response provenance unavailable")

    unknown.decide = lose_provenance  # type: ignore[method-assign]
    workspace = tmp_path / "v2-unknown-attempt-workspace"
    result = ConcurrentRobustnessStudy().run(manifest, adapters, workspace)

    assert result.status == ConcurrentRobustnessStudyStatus.RECONCILIATION_REQUIRED
    assert result.logical_provider_attempts == 1
    assert result.physical_provider_attempts == 0
    operational = tmp_path / f".{workspace.name}.two-stage-v2-operational"
    ledger = _jsonl(operational / "cell-00" / "pair_lifecycle.jsonl")
    assert [row["state"] for row in ledger] == ["pending", "reserved", "attempting"]
    assert not (workspace / "two_stage_execution").exists()

    resume_adapters, resume_typed = _v2_adapters(manifest)
    resumed = ConcurrentRobustnessStudy().run(manifest, resume_adapters, workspace)
    assert resumed == result
    assert all(adapter.calls == [] for adapter in resume_typed.values())


def test_v2_missing_observed_model_requires_reconciliation_before_judgment(
    tmp_path: Path,
) -> None:
    source = _make_validation_report_source(tmp_path, "v2-missing-model-source")
    manifest = _v2_manifest(source, output_identity="v2-missing-model")
    adapters, typed_adapters = _v2_adapters(manifest)
    first_cell_id = manifest.prompt_model_cells[0].cell_id
    typed_adapters[first_cell_id].observed_model = ""
    workspace = tmp_path / "v2-missing-model-workspace"

    result = ConcurrentRobustnessStudy().run(manifest, adapters, workspace)

    assert result.status == ConcurrentRobustnessStudyStatus.RECONCILIATION_REQUIRED
    assert len(typed_adapters[first_cell_id].calls) == 1
    operational = tmp_path / f".{workspace.name}.two-stage-v2-operational"
    ledger = _jsonl(operational / "cell-00" / "pair_lifecycle.jsonl")
    assert [row["state"] for row in ledger] == ["pending", "reserved", "attempting"]
    assert all(row["state"] != "judgment_persisted" for row in ledger)
    assert not (workspace / "two_stage_execution").exists()


def test_v2_preflight_rejects_incomplete_adapter_map_before_any_decision(
    tmp_path: Path,
) -> None:
    source = _make_validation_report_source(tmp_path, "v2-adapter-preflight-source")
    manifest = _v2_manifest(source, output_identity="v2-adapter-preflight")
    adapters, typed_adapters = _v2_adapters(manifest)
    adapters.pop(manifest.prompt_model_cells[-1].cell_id)
    workspace = tmp_path / "v2-adapter-preflight-workspace"

    with pytest.raises(v2_module.ConcurrentRobustnessError) as captured:
        ConcurrentRobustnessStudy().run(manifest, adapters, workspace)

    assert captured.value.code == v2_module.ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS
    assert all(adapter.calls == [] for adapter in typed_adapters.values())
    assert not (tmp_path / f".{workspace.name}.two-stage-v2-operational").exists()


def test_v2_completed_execution_rejects_tampering_before_adapter_calls(
    tmp_path: Path,
) -> None:
    source = _make_validation_report_source(tmp_path, "v2-tamper-source")
    manifest = _v2_manifest(source, output_identity="v2-tamper")
    adapters, _ = _v2_adapters(manifest)
    workspace = tmp_path / "v2-tamper-workspace"
    result = ConcurrentRobustnessStudy().run(manifest, adapters, workspace)
    assert result.status == ConcurrentRobustnessStudyStatus.CELLS_COMPLETE
    execution = workspace / "two_stage_execution"

    for relative_path in (
        "terminal_rows.jsonl",
        "batch_commits.jsonl",
        "pair_lifecycle.jsonl",
        "cell_registry.json",
    ):
        target = execution / relative_path
        original = target.read_bytes()
        target.write_bytes(original + b" ")
        replay_adapters, replay_typed = _v2_adapters(manifest)
        with pytest.raises(v2_module.ConcurrentRobustnessError) as captured:
            ConcurrentRobustnessStudy().run(manifest, replay_adapters, workspace)
        assert captured.value.code == v2_module.ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT
        assert all(adapter.calls == [] for adapter in replay_typed.values())
        target.write_bytes(original)

    terminal_path = execution / "terminal_rows.jsonl"
    execution_manifest_path = execution / "execution_manifest.json"
    terminal_before = terminal_path.read_bytes()
    execution_manifest_before = execution_manifest_path.read_bytes()
    terminal_path.write_bytes(terminal_before + b" ")
    execution_manifest = json.loads(execution_manifest_before)
    execution_manifest["artifacts"]["terminal_rows.jsonl"] = {
        "sha256": hashlib.sha256(terminal_path.read_bytes()).hexdigest(),
        "bytes": terminal_path.stat().st_size,
    }
    execution_manifest_path.write_text(
        json.dumps(
            execution_manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    replay_adapters, replay_typed = _v2_adapters(manifest)
    with pytest.raises(v2_module.ConcurrentRobustnessError) as captured:
        ConcurrentRobustnessStudy().run(manifest, replay_adapters, workspace)
    assert captured.value.code == v2_module.ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT
    assert all(adapter.calls == [] for adapter in replay_typed.values())
    terminal_path.write_bytes(terminal_before)
    execution_manifest_path.write_bytes(execution_manifest_before)
