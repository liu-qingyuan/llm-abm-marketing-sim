from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from llm_abm_sim._concurrent_runtime_spool import _ConcurrentRuntimeBatchSpool


def _write_one_chunk(tmp_path: Path) -> tuple[_ConcurrentRuntimeBatchSpool, Path, dict[str, object]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spool = _ConcurrentRuntimeBatchSpool(
        workspace,
        run_id="runtime-test",
        identity_hash="a" * 64,
        terminal_variants=("primary",),
    )
    ref = spool.prepare_batch(
        time_step=0,
        batch_snapshot_hash="b" * 64,
        commit={
            "time_step": 0,
            "frozen_campaign_engaged_user_ids": [],
            "committed_primary_positive_user_ids": ["u1"],
            "message_summaries": [],
        },
        candidate_rows=[{"time_step": 0, "message_id": "m1", "user_id": "u1"}],
        result_rows=[
            {
                "pair_id": "u1:m1:0",
                "pair_schedule_position": 0,
                "time_step": 0,
                "message_id": "m1",
                "user_id": "u1",
                "primary_status": "succeeded",
                "primary_action": "like",
                "campaign_feedback_committed": "true",
            }
        ],
        terminal_rows=[
            {
                "pair_id": "u1:m1:0",
                "pair_schedule_position": 0,
                "time_step": 0,
                "message_id": "m1",
                "user_id": "u1",
                "decision_variant": "primary",
            }
        ],
        variant_evidence_rows=[
            {
                "pair_id": "u1:m1:0",
                "message_id": "m1",
                "user_id": "u1",
                "decision_variant": "primary",
            }
        ],
    )
    spool.publish_prepared(ref)
    replay = {
        "status": {"committed_batch_count": 1},
        "records": [
            {
                "record_type": "event",
                "event_type": "batch_committed",
                "event_identity": {"time_step": 0},
                "batch_snapshot_hash": "b" * 64,
                "payload": {
                    "time_step": 0,
                    "committed_user_ids": ["u1"],
                    "batch_pair_count": 1,
                    "batch_spool_chunk": ref,
                },
            }
        ],
    }
    return spool, workspace / "concurrent_runtime_batch_spool" / "batch-000000.json", replay


def _ref(replay: dict[str, object]) -> dict[str, object]:
    records = replay["records"]
    assert isinstance(records, list)
    payload = records[0]["payload"]
    assert isinstance(payload, dict)
    ref = payload["batch_spool_chunk"]
    assert isinstance(ref, dict)
    return ref


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_runtime_batch_spool_replays_canonical_rows(tmp_path: Path) -> None:
    spool, chunk_path, replay = _write_one_chunk(tmp_path)

    materialized = spool.materialize(replay)

    assert chunk_path.is_file() and not chunk_path.is_symlink()
    assert [row["user_id"] for row in materialized.candidate_rows] == ["u1"]
    assert [row["pair_id"] for row in materialized.result_rows] == ["u1:m1:0"]
    assert [row["decision_variant"] for row in materialized.terminal_rows] == ["primary"]
    assert materialized.commits[0]["committed_primary_positive_user_ids"] == ["u1"]


@pytest.mark.parametrize(
    ("corruption", "error"),
    [
        ("partial", "partial or invalid"),
        ("missing", "inventory mismatch"),
        ("extra", "inventory mismatch"),
        ("crossed_identity", "chunk identity mismatch"),
        ("checksum", "checksum mismatch"),
        ("symlink", "regular file, not a symlink"),
        ("path_escape", "escapes its private spool directory"),
    ],
)
def test_runtime_batch_spool_fails_closed_on_corruption(
    tmp_path: Path,
    corruption: str,
    error: str,
) -> None:
    spool, chunk_path, original_replay = _write_one_chunk(tmp_path)
    replay = copy.deepcopy(original_replay)
    ref = _ref(replay)

    if corruption == "partial":
        chunk_path.write_bytes(chunk_path.read_bytes() + b"\n{")
        ref["sha256"] = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
    elif corruption == "missing":
        chunk_path.unlink()
    elif corruption == "extra":
        chunk_path.with_name("batch-000001.json").write_bytes(chunk_path.read_bytes())
    elif corruption == "crossed_identity":
        document = json.loads(chunk_path.read_text(encoding="utf-8"))
        document["chunk_identity"]["run_id"] = "crossed-runtime"
        chunk_path.write_bytes(_canonical_bytes(document))
        ref["sha256"] = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
    elif corruption == "checksum":
        chunk_path.write_bytes(chunk_path.read_bytes() + b"\n")
    elif corruption == "symlink":
        outside = tmp_path / "outside.json"
        chunk_path.replace(outside)
        chunk_path.symlink_to(outside)
    else:
        ref["relative_path"] = "../outside.json"

    with pytest.raises((FileNotFoundError, ValueError), match=error):
        spool.materialize(replay)
