#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from llm_abm_sim.concurrent_message_report import close_concurrent_message_artifacts
from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessManifest, ConcurrentRobustnessStudy
from llm_abm_sim.decision import EngageDecision, LLMDecisionAdapter
from llm_abm_sim.prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from llm_abm_sim.provider_request_contract import STRUCTURED_OUTPUT_SCHEMA_HASH
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter
from llm_abm_sim.providers.pi_subscription import (
    PI_SUBSCRIPTION_ADAPTER_IDENTITY,
    PiSubscriptionProviderClient,
)
from llm_abm_sim.schemas import FailClosedAction, ProviderLLMConfig, ReasoningEffort

MODELS = (
    "gpt-5.4-mini",
    "gpt-5.4-2026-03-05",
    "gpt-5.5-2026-04-23",
    "gpt-5.6-sol",
)
COMPONENTS = (
    "base_network_relevance",
    "campaign_engaged_neighbor_signal",
    "normalized_message_user_fit",
)


def canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def sha256_payload(payload: object) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload))


def weight_points() -> list[dict[str, object]]:
    baseline: dict[str, float] = dict(zip(COMPONENTS, (0.50, 0.30, 0.20), strict=True))
    points: list[dict[str, object]] = [
        {
            "scenario_id": "baseline",
            "weights": baseline,
            "transfer_from": None,
            "transfer_to": None,
            "transfer_mass": 0.0,
        }
    ]
    for left, right in ((COMPONENTS[0], COMPONENTS[1]), (COMPONENTS[0], COMPONENTS[2]), (COMPONENTS[1], COMPONENTS[2])):
        for transfer in (0.05, 0.10, 0.15):
            for source, target in ((left, right), (right, left)):
                weights = dict(baseline)
                weights[source] -= transfer
                weights[target] += transfer
                points.append(
                    {
                        "scenario_id": f"transfer-{source}-to-{target}-{transfer:.2f}",
                        "weights": weights,
                        "transfer_from": source,
                        "transfer_to": target,
                        "transfer_mass": transfer,
                    }
                )
    return points


def qualify(contract_dir: Path) -> Path:
    if contract_dir.exists() and any(contract_dir.iterdir()):
        raise FileExistsError(f"qualification contract directory is not empty: {contract_dir}")
    contract_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    with PiSubscriptionProviderClient(response_timeout_seconds=75.0) as client:
        for requested_model in MODELS:
            response = client.create_response(
                [
                    {
                        "role": "system",
                        "content": "你是结构化决策函数。只返回符合 schema 的短 JSON，不要 Markdown。",
                    },
                    {
                        "role": "user",
                        "content": "资格检查：环保酒店内容与用户环保偏好一致。返回一次结构化互动决策。",
                    },
                ],
                requested_model,
                reasoning_effort="low",
                output_token_ceiling=256,
            )
            EngageDecision.model_validate_json(response.decision_text)
            evidence = {
                "schema_version": "concurrent-robustness-subscription-qualification-row-v1",
                "provider_interface": "openai_compatible",
                "provider_transport": "openai-codex",
                "authentication": "local_oauth_subscription",
                "requested_model": requested_model,
                "observed_model": response.observed_model,
                "status": "qualified",
                "structured_decision_valid": True,
                "usage_status": response.usage_status,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "total_tokens": response.total_tokens,
                "cached_input_tokens": response.cached_input_tokens,
                "subscription_nominal_reference_cost_usd": client.last_subscription_nominal_cost_usd,
                "subscription_billed_cost_usd": 0.0,
                "reasoning_effort": "low",
                "output_token_ceiling": 256,
                "output_token_ceiling_enforcement": "application_fail_closed",
                "raw_prompt_persisted": False,
                "raw_response_persisted": False,
            }
            rows.append({**evidence, "evidence_sha256": sha256_payload(evidence)})
    document = {
        "schema_version": "concurrent-robustness-subscription-qualification-v1",
        "provider_transport": "openai-codex",
        "subscription_billing": True,
        "model_count": len(rows),
        "rows": rows,
    }
    output = contract_dir / "model_qualifications.json"
    write_json(output, document)
    return output


def build_manifest(
    *,
    source_dir: Path,
    output_identity: str,
    contract_dir: Path,
) -> ConcurrentRobustnessManifest:
    qualification_path = contract_dir / "model_qualifications.json"
    qualifications_document = json.loads(qualification_path.read_text(encoding="utf-8"))
    qualification_rows = qualifications_document.get("rows")
    if (
        qualifications_document.get("schema_version") != "concurrent-robustness-subscription-qualification-v1"
        or qualifications_document.get("provider_transport") != "openai-codex"
        or qualifications_document.get("subscription_billing") is not True
        or qualifications_document.get("model_count") != 4
        or not isinstance(qualification_rows, list)
        or len(qualification_rows) != 4
    ):
        raise ValueError("qualification artifact header is invalid")
    for row in qualification_rows:
        if not isinstance(row, dict):
            raise ValueError("qualification artifact row is invalid")
        evidence = dict(row)
        recorded_sha256 = evidence.pop("evidence_sha256", None)
        if recorded_sha256 != sha256_payload(evidence):
            raise ValueError("qualification artifact row hash is crossed")
        if (
            row.get("provider_interface") != "openai_compatible"
            or row.get("provider_transport") != "openai-codex"
            or row.get("authentication") != "local_oauth_subscription"
            or row.get("status") != "qualified"
            or row.get("structured_decision_valid") is not True
            or row.get("usage_status") != "complete"
        ):
            raise ValueError("qualification artifact row contract is invalid")
    observed_by_requested = {
        str(row["requested_model"]): str(row["observed_model"])
        for row in qualification_rows
        if isinstance(row, dict)
    }
    if tuple(observed_by_requested) != MODELS:
        raise ValueError("qualification artifact model order is crossed")

    closure = close_concurrent_message_artifacts(source_dir)
    config = closure.source_evidence.config_snapshot
    if config.get("configuration_profile") != "production" or config.get("production_deploy_eligible") is not True:
        raise ValueError("robustness Formal execution requires a deploy-eligible historical Formal source")
    source_hashes = closure.artifact_hashes
    sample_rows = closure.source_evidence.sample_manifest_rows
    sample_identity = hashlib.sha256(
        json.dumps(
            [str(row["user_id"]) for row in sample_rows],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    prompt_cells = [
        {
            "cell_id": f"{prompt.variant_id}::{model}",
            "prompt_variant": prompt.variant_id,
            "prompt_version": prompt.prompt_version,
            "prompt_canonical_hash": prompt.canonical_hash,
            "requested_model": model,
            "required_observed_model": observed_by_requested[model],
        }
        for prompt in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
        for model in MODELS
    ]
    cell_ids = [str(cell["cell_id"]) for cell in prompt_cells]
    logical_per_cell = int(config["horizon"]) * int(config["delivery_capacity"]) * 3
    authorization_reference = f"github:#161:{output_identity}"
    authorization_evidence = {
        "schema_version": "concurrent-robustness-subscription-authorization-evidence-v1",
        "authorization_reference": authorization_reference,
        "authorization_source": "explicit user instruction in issue #161 conversation",
        "provider_transport": "openai-codex",
        "subscription_billing": True,
        "allowed_cell_ids": cell_ids,
        "logical_judgment_cap": logical_per_cell * 16,
        "physical_attempt_cap": logical_per_cell * 16 * 3,
        "fee_ceiling_usd": 0.0,
        "external_requests_allowed": True,
        "canonical_deployment_after_formal_validation": True,
        "production_deploy_eligible": False,
    }
    authorization_sha = sha256_payload(authorization_evidence)
    write_json(
        contract_dir / "execution_authorization.json",
        {**authorization_evidence, "evidence_sha256": authorization_sha},
    )
    pricing_evidence = {
        "schema_version": "concurrent-robustness-subscription-pricing-v1",
        "provider_transport": "openai-codex",
        "billing_mode": "subscription",
        "currency": "USD",
        "input_token_ceiling": 4096,
        "model_pricing": [
            {
                "requested_model": model,
                "input_usd_per_million_tokens": 0.0,
                "output_usd_per_million_tokens": 0.0,
            }
            for model in MODELS
        ],
    }
    pricing_sha = sha256_payload(pricing_evidence)
    write_json(contract_dir / "pricing_snapshot.json", {**pricing_evidence, "evidence_sha256": pricing_sha})

    payload = {
        "schema_version": "concurrent-robustness-manifest-v1",
        "source": {
            "kind": "formal",
            "source_id": source_dir.name,
            "source_dir": str(source_dir.resolve()),
            "manifest_schema": closure.manifest.schema_version,
            "manifest_sha256": source_hashes["artifact_manifest.json"],
            "artifacts": [
                {"relative_path": path, "sha256": digest}
                for path, digest in sorted(source_hashes.items())
            ],
            "candidate_artifact": "concurrent_runtime_candidates.csv",
            "feedback_artifact": "concurrent_runtime_steps.json",
        },
        "sample": {
            "sample_size": len(sample_rows),
            "sample_identity": sample_identity,
            "sample_manifest_sha256": source_hashes["sample_manifest.json"],
            "sample_audit_sha256": source_hashes["seed_first_sample_audit.json"],
        },
        "message_ids": [str(row["message_id"]) for row in closure.source_evidence.message_snapshot],
        "message_snapshot_sha256": source_hashes["message_snapshot.json"],
        "ranking_contract": {
            "schema_version": "concurrent-robustness-ranking-contract-v1",
            "p95_normalization_token": "holdout-safe-log1p-p95-weighted-degree-v1",
            "component_contract_token": "concurrent-ranking-components-v1",
            "components": list(COMPONENTS),
            "tie_break_token": "score-desc-user-id-asc-v1",
            "schedule_token": "shared-seed-launch-then-per-message-top-k-v1",
            "score_precision_token": "binary64-full-precision-no-rounding-v1",
            "ranking_formula": config["ranking_formula"],
            "feedback_formula": config["engaged_neighbor_formula"],
            "horizon": int(config["horizon"]),
            "delivery_capacity": int(config["delivery_capacity"]),
        },
        "weight_points": weight_points(),
        "prompt_model_cells": prompt_cells,
        "request_contract": {
            "schema_version": "provider-request-contract-v1",
            "provider": "openai_compatible",
            "wire_api": "responses",
            "reasoning_effort": "low",
            "output_token_ceiling": 256,
            "timeout_seconds": 30.0,
            "max_retries": 2,
            "retry_backoff_seconds": 0.5,
            "structured_output_schema_version": "engage-decision-output-v1",
            "structured_output_schema_hash": STRUCTURED_OUTPUT_SCHEMA_HASH,
            "omitted_parameters": ["temperature", "top_p", "seed"],
            "decision_store_policy": "fresh-per-cell-no-cache-v1",
        },
        "request_caps": {
            "weight_logical_judgment_cap": 0,
            "logical_judgments_per_cell": logical_per_cell,
            "logical_judgment_cap": logical_per_cell * 16,
            "physical_attempt_cap": logical_per_cell * 16 * 3,
            "fee_ceiling_usd": 0.0,
        },
        "practical_thresholds": {
            "engagement_rate_absolute": 0.05,
            "decision_probability_absolute": 0.05,
            "audience_jaccard_distance": 0.10,
            "terminal_unique_positive_user_fraction": 0.05,
            "terminal_unique_positive_user_count": math.ceil(len(sample_rows) * 0.05),
        },
        "authorization_reference": authorization_reference,
        "output_identity": output_identity,
        "dynamic_execution": {
            "schema_version": "concurrent-robustness-dynamic-execution-v1",
            "profile": "formal_live",
            "provider": "openai_compatible",
            "adapter_identity": PI_SUBSCRIPTION_ADAPTER_IDENTITY,
            "observed_model_policy": "exact-required-model-per-response-v1",
            "stopping_rule": "reject-next-attempt-before-cap-v1",
            "authorization": {
                "schema_version": "concurrent-robustness-execution-authorization-v1",
                "authorization_kind": "formal_live_provider",
                "authorization_reference": authorization_reference,
                "artifact_sha256": authorization_sha,
                "source_manifest_sha256": source_hashes["artifact_manifest.json"],
                "output_identity": output_identity,
                "allowed_cell_ids": cell_ids,
                "logical_judgment_cap": logical_per_cell * 16,
                "physical_attempt_cap": logical_per_cell * 16 * 3,
                "fee_ceiling_usd": 0.0,
                "external_requests_allowed": True,
                "production_deploy_eligible": False,
            },
            "qualifications": [
                {
                    "schema_version": "concurrent-robustness-model-qualification-v1",
                    "qualification_kind": "provider_observed",
                    "artifact_reference": f"{qualification_path.resolve()}#{row['requested_model']}",
                    "artifact_sha256": row["evidence_sha256"],
                    "provider": "openai_compatible",
                    "requested_model": row["requested_model"],
                    "required_observed_model": row["observed_model"],
                    "status": "qualified",
                }
                for row in qualification_rows
            ],
            "pricing_snapshot": {
                "schema_version": "concurrent-robustness-pricing-snapshot-v1",
                "snapshot_reference": str((contract_dir / "pricing_snapshot.json").resolve()),
                "snapshot_sha256": pricing_sha,
                "currency": "USD",
                "input_token_ceiling": 4096,
                "model_pricing": pricing_evidence["model_pricing"],
            },
        },
    }
    manifest = ConcurrentRobustnessManifest.model_validate(payload)
    write_json(contract_dir / "study_manifest.json", manifest.model_dump(mode="json"))
    write_json(
        contract_dir / "formal_run_contract.json",
        {
            "schema_version": "concurrent-robustness-formal-run-contract-v1",
            "output_identity": output_identity,
            "source_dir": str(source_dir.resolve()),
            "workspace": None,
            "study_manifest_sha256": sha256_payload(manifest.model_dump(mode="json")),
            "qualification_artifact": str(qualification_path.resolve()),
            "authorization_artifact": str((contract_dir / "execution_authorization.json").resolve()),
            "pricing_artifact": str((contract_dir / "pricing_snapshot.json").resolve()),
            "provider_calls_authorized": True,
            "canonical_deployment_authorized_after_validation": True,
        },
    )
    return manifest


def build_adapters(
    manifest: ConcurrentRobustnessManifest,
    client: PiSubscriptionProviderClient,
) -> dict[str, LLMDecisionAdapter]:
    adapters: dict[str, LLMDecisionAdapter] = {}
    for cell in manifest.prompt_model_cells:
        adapters[cell.cell_id] = OpenAICompatibleDecisionAdapter(
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
    return adapters


def run_formal(args: argparse.Namespace) -> None:
    manifest = build_manifest(
        source_dir=args.source_dir,
        output_identity=args.output_identity,
        contract_dir=args.contract_dir,
    )
    contract_path = args.contract_dir / "formal_run_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["workspace"] = str(args.output_dir.resolve())
    contract["study_root"] = str(args.output_dir.with_name(f"{args.output_dir.name}.study-root").resolve())
    contract["report_candidate"] = str(args.report_destination.resolve())
    write_json(contract_path, contract)
    with PiSubscriptionProviderClient(
        response_timeout_seconds=manifest.request_contract.timeout_seconds
    ) as client:
        adapters = build_adapters(manifest, client)
        result = ConcurrentRobustnessStudy().run(
            manifest,
            adapters,
            args.output_dir,
            report_destination=args.report_destination,
        )
        subscription_nominal_cost_usd = client.subscription_nominal_cost_usd_total
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["completion_status"] = result.status.value
    contract["logical_provider_attempts"] = result.logical_provider_attempts
    contract["physical_provider_attempts"] = result.physical_provider_attempts
    contract["subscription_nominal_reference_cost_usd"] = subscription_nominal_cost_usd
    contract["subscription_billed_cost_usd"] = 0.0
    contract["subscription_billing_evidence"] = "openai-codex OAuth subscription transport"
    write_json(contract_path, contract)
    print(
        json.dumps(
            {
                "status": result.status.value,
                "workspace": str(result.workspace_root),
                "study_root": str(result.study_root) if result.study_root else None,
                "report_candidate": str(result.report_candidate) if result.report_candidate else None,
                "logical_provider_attempts": result.logical_provider_attempts,
                "physical_provider_attempts": result.physical_provider_attempts,
                "manifest_sha256": result.manifest_sha256,
            },
            ensure_ascii=False,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qualify or run the subscription-backed Concurrent Robustness Formal study")
    subparsers = parser.add_subparsers(dest="command", required=True)
    qualify_parser = subparsers.add_parser("qualify")
    qualify_parser.add_argument("--contract-dir", type=Path, required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--source-dir", type=Path, required=True)
    run_parser.add_argument("--contract-dir", type=Path, required=True)
    run_parser.add_argument("--output-identity", required=True)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--report-destination", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1":
        raise SystemExit("Formal robustness requires LLM_ABM_RUN_LIVE_LLM=1")
    args = parse_args()
    if args.command == "qualify":
        print(qualify(args.contract_dir))
    else:
        run_formal(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
