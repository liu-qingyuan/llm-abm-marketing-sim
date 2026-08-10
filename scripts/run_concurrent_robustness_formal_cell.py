#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path

from llm_abm_sim.concurrent_message_experiment import _PrimaryOnlyConcurrentRuntimeConsumer
from llm_abm_sim.concurrent_robustness_study import (
    ConcurrentRobustnessManifest,
    _build_dynamic_cell_evidence,
    _cell_execution_identity,
    _cell_output_target,
    _close_source,
    _dynamic_root,
    _dynamic_runtime_config,
    _json_bytes,
    _preflight_dynamic_adapters,
    _resolve_source_path,
    _sha256_bytes,
    _validate_dynamic_initial_state,
    _validate_dynamic_terminal,
    _validate_source_against_manifest,
)
from llm_abm_sim.decision import LLMDecisionAdapter
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter
from llm_abm_sim.providers.pi_subscription import PiSubscriptionProviderClient
from llm_abm_sim.schemas import FailClosedAction, ProviderLLMConfig, ReasoningEffort


class CellBudgetGuard:
    def __init__(self, *, logical_cap: int, physical_cap: int, max_retries: int) -> None:
        self.logical_cap = logical_cap
        self.physical_cap = physical_cap
        self.max_attempts = max_retries + 1
        self.logical_judgments = 0
        self.physical_attempts = 0
        self.pending_pair_id: str | None = None

    def before(self, judgment: Mapping[str, object]) -> None:
        if self.pending_pair_id is not None:
            raise RuntimeError("cell worker budget lifecycle is crossed")
        if (
            self.logical_judgments + 1 > self.logical_cap
            or self.physical_attempts + self.max_attempts > self.physical_cap
        ):
            raise RuntimeError("cell worker would exceed its frozen logical or physical cap")
        pair_id = judgment.get("pair_id")
        if not isinstance(pair_id, str) or not pair_id:
            raise ValueError("cell worker judgment identity is invalid")
        self.pending_pair_id = pair_id

    def after(self, evidence: Mapping[str, object]) -> None:
        if self.pending_pair_id is None or evidence.get("pair_id") != self.pending_pair_id:
            raise RuntimeError("cell worker terminal identity is crossed")
        invocations = evidence.get("request_invocations")
        if type(invocations) is not int or not 1 <= invocations <= self.max_attempts:
            raise ValueError("cell worker terminal physical attempts violate the retry contract")
        self.logical_judgments += 1
        self.physical_attempts += invocations
        self.pending_pair_id = None


def build_adapters(
    manifest: ConcurrentRobustnessManifest,
    client: PiSubscriptionProviderClient,
) -> dict[str, LLMDecisionAdapter]:
    return {
        cell.cell_id: OpenAICompatibleDecisionAdapter(
            ProviderLLMConfig(
                enabled=True,
                provider="openai_compatible",
                model=cell.requested_model,
                wire_api="responses",
                require_live_env=True,
                timeout_seconds=manifest.request_contract.timeout_seconds,
                max_retries=manifest.request_contract.max_retries,
                retry_backoff_seconds=manifest.request_contract.retry_backoff_seconds,
                fail_closed_action=FailClosedAction.RAISE,
                prompt_version=cell.prompt_version,
                reasoning_effort=ReasoningEffort.LOW,
                max_output_tokens=manifest.request_contract.output_token_ceiling,
            ),
            client=client,
        )
        for cell in manifest.prompt_model_cells
    }


def run_cell(*, manifest_path: Path, output_dir: Path, cell_index: int) -> dict[str, object]:
    manifest_payload = manifest_path.read_bytes()
    manifest = ConcurrentRobustnessManifest.model_validate_json(manifest_payload)
    if manifest.dynamic_execution is None or manifest.dynamic_execution.profile != "formal_live":
        raise ValueError("single-cell worker requires the Formal dynamic execution profile")
    if not 0 <= cell_index < len(manifest.prompt_model_cells):
        raise ValueError("cell index is outside the frozen manifest")
    manifest_sha256 = _sha256_bytes(_json_bytes(manifest.model_dump(mode="json")))
    if manifest_payload != _json_bytes(manifest.model_dump(mode="json")):
        raise ValueError("persisted study manifest is not canonical")
    source_path = _resolve_source_path(manifest.source.source_dir)
    closure = _close_source(source_path)
    _validate_source_against_manifest(manifest, closure, source_path)
    root = _dynamic_root(output_dir.resolve())
    if root.is_symlink() or not root.is_dir():
        raise ValueError("main Formal dynamic root must exist before cell workers start")
    output_target = _cell_output_target(root, cell_index)
    workspace = output_target.parent / f".{output_target.name}.operational"
    if output_target.exists() or workspace.exists():
        raise FileExistsError("cell worker refuses an existing target or operational journal")

    logical_cap = manifest.request_caps.logical_judgments_per_cell
    physical_cap = logical_cap * (manifest.request_contract.max_retries + 1)
    guard = CellBudgetGuard(
        logical_cap=logical_cap,
        physical_cap=physical_cap,
        max_retries=manifest.request_contract.max_retries,
    )
    with PiSubscriptionProviderClient(
        response_timeout_seconds=manifest.request_contract.timeout_seconds
    ) as client:
        preflight = _preflight_dynamic_adapters(manifest, build_adapters(manifest, client))
        cell, adapter = preflight.adapters[cell_index]
        baseline = preflight.external_request_baselines[cell.cell_id]

        def validate_terminal(evidence: Mapping[str, object]) -> None:
            _validate_dynamic_terminal(
                evidence,
                manifest=manifest,
                cell=cell,
                adapter=adapter,
                external_baseline=baseline,
            )

        consumer = _PrimaryOnlyConcurrentRuntimeConsumer(
            _dynamic_runtime_config(closure),
            adapter,
            expected_prompt_version=cell.prompt_version,
            execution_contract=_cell_execution_identity(
                manifest=manifest,
                manifest_sha256=manifest_sha256,
                cell_index=cell_index,
                cell=cell,
            ),
            expected_sample_identity=manifest.sample.sample_identity,
            before_logical_judgment=guard.before,
            validate_terminal=validate_terminal,
            after_logical_judgment=guard.after,
        )
        result = consumer.run_new(output_target)
        nominal_reference_cost_usd = client.subscription_nominal_cost_usd_total
    _validate_dynamic_initial_state(
        result,
        source_candidate_rows=closure.source_evidence.candidate_rows,
    )
    evidence = _build_dynamic_cell_evidence(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        cell_index=cell_index,
        cell=cell,
        result=result,
    )
    if (
        evidence.logical_judgment_count != logical_cap
        or evidence.physical_attempt_count != guard.physical_attempts
        or guard.logical_judgments != logical_cap
    ):
        raise ValueError("single-cell worker did not close its complete frozen schedule")
    summary = {
        "schema_version": "concurrent-robustness-formal-cell-worker-completion-v1",
        "manifest_sha256": manifest_sha256,
        "cell_index": cell_index,
        "cell_id": cell.cell_id,
        "requested_model": cell.requested_model,
        "observed_model": cell.required_observed_model,
        "logical_judgments": evidence.logical_judgment_count,
        "physical_attempts": evidence.physical_attempt_count,
        "subscription_nominal_reference_cost_usd": nominal_reference_cost_usd,
        "subscription_billed_cost_usd": 0.0,
        "journal_workspace": str(result.workspace_root.resolve()),
        "production_deploy_eligible": False,
    }
    completion_path = output_target.parent / "cell_worker_completion.json"
    temporary = completion_path.with_suffix(".json.tmp")
    temporary.write_bytes(_json_bytes(summary))
    os.replace(temporary, completion_path)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one disjoint Formal Prompt-Model cell")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cell-index", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1":
        raise SystemExit("Formal cell worker requires LLM_ABM_RUN_LIVE_LLM=1")
    args = parse_args()
    print(json.dumps(run_cell(manifest_path=args.manifest, output_dir=args.output_dir, cell_index=args.cell_index)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
