from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_abm_sim.concurrent_execution_journal import (
    CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL,
    CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR,
    ConcurrentExecutionJournal,
    build_concurrent_execution_run_identity,
    derive_concurrent_execution_workspace,
)


def _write_csv(path: Path, header: str, *rows: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join((header, *rows)) + "\n", encoding="utf-8")


def _make_dataset_dir(tmp_path: Path) -> Path:
    dataset_dir = tmp_path / "dataset"
    _write_csv(dataset_dir / "videos.csv", "video_id", "holdout-video")
    _write_csv(dataset_dir / "users.csv", "user_id", "u1", "u2")
    _write_csv(dataset_dir / "comments.csv", "comment_id", "c1")
    return dataset_dir


def test_concurrent_execution_journal_tracks_completion_and_rejects_checksum_tamper(tmp_path: Path) -> None:
    dataset_dir = _make_dataset_dir(tmp_path)
    output_target = tmp_path / "final" / "run"
    workspace = derive_concurrent_execution_workspace(output_target)
    identity = build_concurrent_execution_run_identity(
        output_target=output_target,
        operational_workspace=workspace,
        configuration_snapshot={
            "horizon": 1,
            "sample_size": 2,
            "delivery_capacity": 1,
            "configuration_profile": "validation",
        },
        message_snapshot=[
            {
                "message_id": "message_1",
                "title": "Message 1",
                "intended_audience_segment": "class_1",
                "body": "body",
                "value_dimensions": {"environmental": 1.0},
            }
        ],
        sample_audit={"seed_user_ids": ["u1"]},
        dataset_dir=dataset_dir,
        primary_provider_metadata={
            "provider": "mocked",
            "model": "primary-model",
            "timeout_seconds": 1.0,
            "max_retries": 0,
        },
        shadow_provider_metadata={
            "provider": "mocked",
            "model": "shadow-model",
            "timeout_seconds": 1.0,
            "max_retries": 0,
        },
        prompt_contract={"primary": {"prompt_version": "primary-v1"}, "shadow": {"prompt_version": "shadow-v1"}},
    )

    journal = ConcurrentExecutionJournal.open_new(workspace, identity=identity)
    snapshot_ref = journal.persist_snapshot(
        snapshot_type="batch_plan",
        snapshot_identity={"time_step": 0},
        payload={
            "schema_version": "concurrent-message-execution-batch-plan-v1",
            "time_step": 0,
            "frozen_campaign_engaged_user_ids": ["u1"],
            "planned_pair_count": 1,
            "planned_variant_count": 2,
            "messages": [
                {
                    "message_id": "message_1",
                    "message_title": "Message 1",
                    "eligible_users": 2,
                    "ranked_candidates": [
                        {
                            "time_step": 0,
                            "message_id": "message_1",
                            "user_id": "u1",
                        }
                    ],
                    "selected_pair_plans": [
                        {
                            "pair_id": "u1:message_1:0",
                            "pair_schedule_position": 0,
                            "time_step": 0,
                            "message_id": "message_1",
                            "message_title": "Message 1",
                            "user_id": "u1",
                            "ranking_position": 1,
                            "selection_reason": "seed_union",
                            "base_network_relevance": 0.5,
                            "base_network_relevance_full_precision": "0.5",
                            "campaign_engaged_neighbor_count": 0,
                            "campaign_engaged_neighbor_signal": 0.0,
                            "campaign_engaged_neighbor_signal_full_precision": "0",
                            "historical_tag_affinity": 0.0,
                            "raw_message_user_fit": 1.0,
                            "raw_message_user_fit_full_precision": "1",
                            "normalized_message_user_fit": 1.0,
                            "normalized_message_user_fit_full_precision": "1",
                            "personalized_delivery_score": 0.8,
                            "personalized_delivery_score_full_precision": "0.8",
                        }
                    ],
                    "selected_user_ids": ["u1"],
                    "seed_user_ids": ["u1"],
                    "personalized_topup_user_ids": [],
                    "below_delivery_capacity": 0,
                    "selection_reason_counts": {"seed_union": 1},
                }
            ],
        },
    )
    batch_snapshot_hash = snapshot_ref["snapshot_hash"]

    journal.append(
        event_type="variant_started",
        event_identity={"pair_id": "u1:message_1:0", "decision_variant": "primary", "event_type": "variant_started", "time_step": 0},
        payload={"pair_id": "u1:message_1:0", "pair_schedule_position": 0, "message_id": "message_1", "message_title": "Message 1", "user_id": "u1"},
        batch_snapshot_hash=batch_snapshot_hash,
    )
    journal.append(
        event_type="variant_started",
        event_identity={"pair_id": "u1:message_1:0", "decision_variant": "shadow", "event_type": "variant_started", "time_step": 0},
        payload={"pair_id": "u1:message_1:0", "pair_schedule_position": 0, "message_id": "message_1", "message_title": "Message 1", "user_id": "u1"},
        batch_snapshot_hash=batch_snapshot_hash,
    )
    journal.append(
        event_type="variant_terminal",
        event_identity={"pair_id": "u1:message_1:0", "decision_variant": "primary", "event_type": "variant_terminal", "time_step": 0},
        payload={
            "pair_id": "u1:message_1:0",
            "pair_schedule_position": 0,
            "message_id": "message_1",
            "message_title": "Message 1",
            "user_id": "u1",
            "terminal_row_id": "u1:message_1:0:primary",
            "terminal_status": "succeeded",
            "provider_status": "succeeded",
            "action": "ignore",
            "reason": "ok",
            "decision_source": "mock",
        },
        batch_snapshot_hash=batch_snapshot_hash,
    )
    journal.append(
        event_type="variant_terminal",
        event_identity={"pair_id": "u1:message_1:0", "decision_variant": "shadow", "event_type": "variant_terminal", "time_step": 0},
        payload={
            "pair_id": "u1:message_1:0",
            "pair_schedule_position": 0,
            "message_id": "message_1",
            "message_title": "Message 1",
            "user_id": "u1",
            "terminal_row_id": "u1:message_1:0:shadow",
            "terminal_status": "succeeded",
            "provider_status": "succeeded",
            "action": "ignore",
            "reason": "ok",
            "decision_source": "mock",
        },
        batch_snapshot_hash=batch_snapshot_hash,
    )
    journal.append(
        event_type="pair_closed",
        event_identity={"pair_id": "u1:message_1:0", "time_step": 0},
        payload={
            "pair_id": "u1:message_1:0",
            "pair_schedule_position": 0,
            "message_id": "message_1",
            "message_title": "Message 1",
            "user_id": "u1",
            "primary_terminal_row_id": "u1:message_1:0:primary",
            "shadow_terminal_row_id": "u1:message_1:0:shadow",
            "primary_status": "succeeded",
            "shadow_status": "succeeded",
        },
        batch_snapshot_hash=batch_snapshot_hash,
    )
    journal.append(
        event_type="batch_committed",
        event_identity={"time_step": 0},
        payload={"time_step": 0, "committed_user_ids": ["u1"], "committed_user_count": 1, "batch_pair_count": 1},
        batch_snapshot_hash=batch_snapshot_hash,
    )
    journal.append(
        event_type="run_finalized",
        event_identity={"run_id": journal.run_id, "output_target": str(output_target)},
        payload={"output_target": str(output_target), "operational_workspace": str(workspace), "report_path": str(output_target / "report.html")},
    )

    status = journal.status()
    assert status["lifecycle"] == "durable_partial"
    assert status["finalization_started"] is True
    assert status["final_source_path"] == str(output_target)
    assert status["planned_batch_count"] == 1
    assert status["planned_pair_count"] == 1
    assert status["planned_variant_count"] == 2
    assert status["started_variant_count"] == 2
    assert status["terminal_variant_count"] == 2
    assert status["closed_pair_count"] == 1
    assert status["committed_batch_count"] == 1
    assert status["last_durable_identity"]["event_type"] == "run_finalized"
    assert (workspace / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL).is_file()
    assert (workspace / CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR).is_dir()

    journal_lines = (workspace / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL).read_text(encoding="utf-8").splitlines()
    tampered = json.loads(journal_lines[-1])
    tampered["previous_checksum"] = "deadbeef"
    journal_lines[-1] = json.dumps(tampered, ensure_ascii=False, sort_keys=True)
    (workspace / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL).write_text("\n".join(journal_lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum chain breaks"):
        ConcurrentExecutionJournal.open_existing(workspace).status()



def test_concurrent_execution_journal_replay_and_open_resume_continuity(tmp_path: Path) -> None:
    dataset_dir = _make_dataset_dir(tmp_path)
    output_target = tmp_path / "final" / "run"
    workspace = derive_concurrent_execution_workspace(output_target)
    identity = build_concurrent_execution_run_identity(
        output_target=output_target,
        operational_workspace=workspace,
        configuration_snapshot={
            "horizon": 1,
            "sample_size": 2,
            "delivery_capacity": 1,
            "configuration_profile": "validation",
        },
        message_snapshot=[
            {
                "message_id": "message_1",
                "title": "Message 1",
                "intended_audience_segment": "class_1",
                "body": "body",
                "value_dimensions": {"environmental": 1.0},
            }
        ],
        sample_audit={"seed_user_ids": ["u1"]},
        dataset_dir=dataset_dir,
        primary_provider_metadata={
            "provider": "mocked",
            "model": "primary-model",
            "timeout_seconds": 1.0,
            "max_retries": 0,
        },
        shadow_provider_metadata={
            "provider": "mocked",
            "model": "shadow-model",
            "timeout_seconds": 1.0,
            "max_retries": 0,
        },
        prompt_contract={"primary": {"prompt_version": "primary-v1"}, "shadow": {"prompt_version": "shadow-v1"}},
    )

    journal = ConcurrentExecutionJournal.open_new(workspace, identity=identity)
    snapshot_ref = journal.persist_snapshot(
        snapshot_type="batch_plan",
        snapshot_identity={"time_step": 0},
        payload={
            "schema_version": "concurrent-message-execution-batch-plan-v1",
            "time_step": 0,
            "frozen_campaign_engaged_user_ids": ["u1"],
            "planned_pair_count": 1,
            "planned_variant_count": 2,
            "messages": [
                {
                    "message_id": "message_1",
                    "message_title": "Message 1",
                    "eligible_users": 2,
                    "ranked_candidates": [
                        {
                            "time_step": 0,
                            "message_id": "message_1",
                            "user_id": "u1",
                        }
                    ],
                    "selected_pair_plans": [
                        {
                            "pair_id": "u1:message_1:0",
                            "pair_schedule_position": 0,
                            "time_step": 0,
                            "message_id": "message_1",
                            "message_title": "Message 1",
                            "user_id": "u1",
                            "ranking_position": 1,
                            "selection_reason": "seed_union",
                            "base_network_relevance": 0.5,
                            "base_network_relevance_full_precision": "0.5",
                            "campaign_engaged_neighbor_count": 0,
                            "campaign_engaged_neighbor_signal": 0.0,
                            "campaign_engaged_neighbor_signal_full_precision": "0",
                            "historical_tag_affinity": 0.0,
                            "raw_message_user_fit": 1.0,
                            "raw_message_user_fit_full_precision": "1",
                            "normalized_message_user_fit": 1.0,
                            "normalized_message_user_fit_full_precision": "1",
                            "personalized_delivery_score": 0.8,
                            "personalized_delivery_score_full_precision": "0.8",
                        }
                    ],
                    "selected_user_ids": ["u1"],
                    "seed_user_ids": ["u1"],
                    "personalized_topup_user_ids": [],
                    "below_delivery_capacity": 0,
                    "selection_reason_counts": {"seed_union": 1},
                }
            ],
        },
    )
    batch_snapshot_hash = snapshot_ref["snapshot_hash"]
    journal.append(
        event_type="variant_started",
        event_identity={"pair_id": "u1:message_1:0", "decision_variant": "primary", "event_type": "variant_started", "time_step": 0},
        payload={"pair_id": "u1:message_1:0", "pair_schedule_position": 0, "message_id": "message_1", "message_title": "Message 1", "user_id": "u1", "ranking_position": 1, "selection_reason": "seed_union"},
        batch_snapshot_hash=batch_snapshot_hash,
    )
    journal.append(
        event_type="variant_started",
        event_identity={"pair_id": "u1:message_1:0", "decision_variant": "shadow", "event_type": "variant_started", "time_step": 0},
        payload={"pair_id": "u1:message_1:0", "pair_schedule_position": 0, "message_id": "message_1", "message_title": "Message 1", "user_id": "u1", "ranking_position": 1, "selection_reason": "seed_union"},
        batch_snapshot_hash=batch_snapshot_hash,
    )
    journal.append(
        event_type="variant_terminal",
        event_identity={"pair_id": "u1:message_1:0", "decision_variant": "primary", "event_type": "variant_terminal", "time_step": 0},
        payload={
            "pair_id": "u1:message_1:0",
            "pair_schedule_position": 0,
            "message_id": "message_1",
            "message_title": "Message 1",
            "user_id": "u1",
            "terminal_row_id": "u1:message_1:0:primary",
            "terminal_status": "succeeded",
            "provider_status": "succeeded",
            "action": "like",
            "reason": "ok",
            "decision_source": "mock",
            "terminal_row": {
                "terminal_row_id": "u1:message_1:0:primary",
                "pair_id": "u1:message_1:0",
                "pair_schedule_position": 0,
                "time_step": 0,
                "message_id": "message_1",
                "user_id": "u1",
                "decision_variant": "primary",
                "prompt_version": "primary-v1",
                "context_source_key": "u1:message_1:0:primary",
                "cache_key": "cache-primary",
                "context_profile_payload": "{}",
                "peer_context_payload": "{}",
                "prompt_field_inclusion": "{}",
                "request_invocations": 1,
                "provider_response_count": 1,
                "successful_decision_count": 1,
                "observed_model_counts": "{}",
                "observed_model_missing_response_count": 0,
                "observed_model_malformed_response_count": 0,
                "usage_complete": "true",
                "usage_complete_response_count": 1,
                "usage_missing_response_count": 0,
                "usage_malformed_response_count": 0,
                "input_usage": 1,
                "output_usage": 1,
                "total_usage": 2,
                "cached_input_usage": 0,
                "terminal_status": "succeeded",
                "provider_status": "succeeded",
                "engage": "true",
                "probability": 0.9,
                "confidence": 0.9,
                "action": "like",
                "reason": "ok",
                "decision_source": "mock",
                "failure_type": "",
                "provider_metadata": "{}",
            },
            "variant_evidence": {
                "terminal_row_id": "u1:message_1:0:primary",
                "pair_id": "u1:message_1:0",
                "message_id": "message_1",
                "user_id": "u1",
                "decision_variant": "primary",
                "prompt_version": "primary-v1",
                "context_source_key": "u1:message_1:0:primary",
                "cache_key": "cache-primary",
                "profile_payload": {},
                "peer_context_payload": {},
                "prompt_field_inclusion": {},
                "request_invocations": 1,
                "provider_response_count": 1,
                "successful_decision_count": 1,
                "observed_model_counts": {},
                "observed_model_missing_response_count": 0,
                "observed_model_malformed_response_count": 0,
                "usage_complete": True,
                "usage_complete_response_count": 1,
                "usage_missing_response_count": 0,
                "usage_malformed_response_count": 0,
                "input_usage": 1,
                "output_usage": 1,
                "total_usage": 2,
                "cached_input_usage": 0,
                "terminal_status": "succeeded",
                "provider_status": "succeeded",
                "action": "like",
                "decision_source": "mock",
            },
        },
        batch_snapshot_hash=batch_snapshot_hash,
    )
    journal.append(
        event_type="variant_terminal",
        event_identity={"pair_id": "u1:message_1:0", "decision_variant": "shadow", "event_type": "variant_terminal", "time_step": 0},
        payload={
            "pair_id": "u1:message_1:0",
            "pair_schedule_position": 0,
            "message_id": "message_1",
            "message_title": "Message 1",
            "user_id": "u1",
            "terminal_row_id": "u1:message_1:0:shadow",
            "terminal_status": "succeeded",
            "provider_status": "succeeded",
            "action": "ignore",
            "reason": "ok",
            "decision_source": "mock",
            "terminal_row": {
                "terminal_row_id": "u1:message_1:0:shadow",
                "pair_id": "u1:message_1:0",
                "pair_schedule_position": 0,
                "time_step": 0,
                "message_id": "message_1",
                "user_id": "u1",
                "decision_variant": "shadow",
                "prompt_version": "shadow-v1",
                "context_source_key": "u1:message_1:0:shadow",
                "cache_key": "cache-shadow",
                "context_profile_payload": "{}",
                "peer_context_payload": "{}",
                "prompt_field_inclusion": "{}",
                "request_invocations": 1,
                "provider_response_count": 1,
                "successful_decision_count": 1,
                "observed_model_counts": "{}",
                "observed_model_missing_response_count": 0,
                "observed_model_malformed_response_count": 0,
                "usage_complete": "true",
                "usage_complete_response_count": 1,
                "usage_missing_response_count": 0,
                "usage_malformed_response_count": 0,
                "input_usage": 1,
                "output_usage": 1,
                "total_usage": 2,
                "cached_input_usage": 0,
                "terminal_status": "succeeded",
                "provider_status": "succeeded",
                "engage": "false",
                "probability": 0.1,
                "confidence": 0.9,
                "action": "ignore",
                "reason": "ok",
                "decision_source": "mock",
                "failure_type": "",
                "provider_metadata": "{}",
            },
            "variant_evidence": {
                "terminal_row_id": "u1:message_1:0:shadow",
                "pair_id": "u1:message_1:0",
                "message_id": "message_1",
                "user_id": "u1",
                "decision_variant": "shadow",
                "prompt_version": "shadow-v1",
                "context_source_key": "u1:message_1:0:shadow",
                "cache_key": "cache-shadow",
                "profile_payload": {},
                "peer_context_payload": {},
                "prompt_field_inclusion": {},
                "request_invocations": 1,
                "provider_response_count": 1,
                "successful_decision_count": 1,
                "observed_model_counts": {},
                "observed_model_missing_response_count": 0,
                "observed_model_malformed_response_count": 0,
                "usage_complete": True,
                "usage_complete_response_count": 1,
                "usage_missing_response_count": 0,
                "usage_malformed_response_count": 0,
                "input_usage": 1,
                "output_usage": 1,
                "total_usage": 2,
                "cached_input_usage": 0,
                "terminal_status": "succeeded",
                "provider_status": "succeeded",
                "action": "ignore",
                "decision_source": "mock",
            },
        },
        batch_snapshot_hash=batch_snapshot_hash,
    )
    journal.append(
        event_type="pair_closed",
        event_identity={"pair_id": "u1:message_1:0", "time_step": 0},
        payload={
            "pair_id": "u1:message_1:0",
            "pair_schedule_position": 0,
            "message_id": "message_1",
            "message_title": "Message 1",
            "user_id": "u1",
            "primary_terminal_row_id": "u1:message_1:0:primary",
            "shadow_terminal_row_id": "u1:message_1:0:shadow",
            "primary_status": "succeeded",
            "shadow_status": "succeeded",
        },
        batch_snapshot_hash=batch_snapshot_hash,
    )

    replay = journal.replay()
    assert replay["records"][1]["snapshot_document"]["payload"]["planned_pair_count"] == 1
    assert replay["records"][2]["payload"]["pair_id"] == "u1:message_1:0"
    assert replay["records"][4]["payload"]["terminal_row"]["action"] == "like"

    journal.close()

    resumed = ConcurrentExecutionJournal.open_resume(workspace, identity=identity)
    assert resumed.sequence == len(replay["records"])
    assert resumed.previous_checksum is not None
    resumed.append(
        event_type="batch_committed",
        event_identity={"time_step": 0},
        payload={"time_step": 0, "committed_user_ids": ["u1"], "committed_user_count": 1, "batch_pair_count": 1},
        batch_snapshot_hash=batch_snapshot_hash,
    )
    resumed.append(
        event_type="run_finalized",
        event_identity={"run_id": resumed.run_id, "output_target": str(output_target)},
        payload={
            "output_target": str(output_target),
            "operational_workspace": str(workspace),
            "report_path": str(output_target / "report.html"),
            "deploy_eligibility": False,
        },
    )
    assert resumed.status()["lifecycle"] == "durable_partial"
    assert resumed.status()["finalization_started"] is True
    resumed.close()

    reopened = ConcurrentExecutionJournal.open_resume(workspace, identity=identity)
    assert reopened.status()["lifecycle"] == "durable_partial"
    reopened.close()


def test_concurrent_execution_journal_open_resume_rejects_lock_contention_and_identity_mismatch(tmp_path: Path) -> None:
    dataset_dir = _make_dataset_dir(tmp_path)
    output_target = tmp_path / "final" / "run"
    workspace = derive_concurrent_execution_workspace(output_target)
    identity = build_concurrent_execution_run_identity(
        output_target=output_target,
        operational_workspace=workspace,
        configuration_snapshot={
            "horizon": 1,
            "sample_size": 2,
            "delivery_capacity": 1,
            "configuration_profile": "validation",
        },
        message_snapshot=[
            {
                "message_id": "message_1",
                "title": "Message 1",
                "intended_audience_segment": "class_1",
                "body": "body",
                "value_dimensions": {"environmental": 1.0},
            }
        ],
        sample_audit={"seed_user_ids": ["u1"]},
        dataset_dir=dataset_dir,
        primary_provider_metadata={
            "provider": "mocked",
            "model": "primary-model",
            "timeout_seconds": 1.0,
            "max_retries": 0,
        },
        shadow_provider_metadata={
            "provider": "mocked",
            "model": "shadow-model",
            "timeout_seconds": 1.0,
            "max_retries": 0,
        },
        prompt_contract={"primary": {"prompt_version": "primary-v1"}, "shadow": {"prompt_version": "shadow-v1"}},
    )

    journal = ConcurrentExecutionJournal.open_new(workspace, identity=identity)
    with pytest.raises((BlockingIOError, OSError)):
        ConcurrentExecutionJournal.open_resume(workspace, identity=identity)
    journal.close()

    mismatched_identity = build_concurrent_execution_run_identity(
        output_target=output_target,
        operational_workspace=workspace,
        configuration_snapshot={
            "horizon": 1,
            "sample_size": 2,
            "delivery_capacity": 2,
            "configuration_profile": "validation",
        },
        message_snapshot=[
            {
                "message_id": "message_1",
                "title": "Message 1",
                "intended_audience_segment": "class_1",
                "body": "body",
                "value_dimensions": {"environmental": 1.0},
            }
        ],
        sample_audit={"seed_user_ids": ["u1"]},
        dataset_dir=dataset_dir,
        primary_provider_metadata={
            "provider": "mocked",
            "model": "primary-model",
            "timeout_seconds": 1.0,
            "max_retries": 0,
        },
        shadow_provider_metadata={
            "provider": "mocked",
            "model": "shadow-model",
            "timeout_seconds": 1.0,
            "max_retries": 0,
        },
        prompt_contract={"primary": {"prompt_version": "primary-v1"}, "shadow": {"prompt_version": "shadow-v1"}},
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        ConcurrentExecutionJournal.open_resume(workspace, identity=mismatched_identity)
