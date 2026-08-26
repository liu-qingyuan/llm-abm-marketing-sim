from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from llm_abm_sim.concurrent_execution_journal import (
    CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON,
)
from llm_abm_sim.decision import DecisionInput, EngageDecision, LLMDecisionAdapter
from llm_abm_sim.full_pool_source_v4 import _ClosedStrictFullPoolSource
from llm_abm_sim.full_pool_strict_replay import (
    StrictFreshReplayStatus,
    StrictFullPoolFormalReplay,
    strict_formal_provider_contract,
)
from llm_abm_sim.full_pool_two_stage_replay import (
    FULL_POOL_TWO_STAGE_EVIDENCE_SCHEMA,
    FULL_POOL_TWO_STAGE_PROJECTION_SCHEMA,
    FULL_POOL_TWO_STAGE_SOURCE_SCHEMA,
    FullPoolTwoStageReplay,
    FullPoolTwoStageReplayRequest,
    _provider_judgment_inventory,
)
from llm_abm_sim.prompt_field_summary import build_prompt_field_summary
from llm_abm_sim.provider_accounting import (
    ProviderAccounting,
    ProviderAccountingTracker,
    ProviderResponseEnvelope,
)
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile
from tests.integration.test_full_pool_strict_replay import _request


class _TwoStageFixtureAdapter(LLMDecisionAdapter):
    def __init__(self, lane_id: int, workspace: Path) -> None:
        self.lane_id = lane_id
        self.workspace = workspace
        self.request_invocations = 0
        self.external_request_invocations = 0
        self.prompt_version = str(strict_formal_provider_contract()["prompt_version"])
        self.safe_metadata = strict_formal_provider_contract()
        self._accounting = ProviderAccountingTracker()
        self._source_identity: str | None = None

    @property
    def provider_accounting(self) -> ProviderAccounting:
        return self._accounting.snapshot(external_request_invocations=0)

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        build_prompt_field_summary(
            DecisionInput(
                post=post,
                profile=profile,
                peer_context=peer_context,
                platform_context=platform_context or PlatformContext(),
                time_step=time_step,
                prompt_version=self.prompt_version,
            )
        )
        self.request_invocations += 1
        self._accounting.record_response(
            ProviderResponseEnvelope(
                decision_text='{"engage":true,"action":"like"}',
                observed_model="gpt-5.6-sol",
                observed_model_status="reported",
                usage_status="complete",
                input_tokens=10,
                output_tokens=2,
                total_tokens=12,
                cached_input_tokens=0,
            )
        )
        self._accounting.record_successful_decision()

        source_identity = self._runtime_source_identity()
        draw = _draw(source_identity, profile.user_id, post.post_id)
        code = (int(profile.user_id.removeprefix("u")) + int(post.post_id.removeprefix("message_"))) % 5
        if code == 0:
            engage, probability, action = False, 0.95, "ignore"
        elif code == 1:
            engage, probability, action = True, 0.0, "like"
        elif code == 2:
            engage, probability, action = True, 1.0, "comment"
        elif code == 3:
            engage, probability, action = True, (draw + 1.0) / 2.0, "share"
        else:
            engage, probability, action = True, draw / 2.0, "like"
        return EngageDecision(
            engage=engage,
            probability=probability,
            confidence=0.73,
            action=action,
            reason=f"provider intent for {profile.user_id}:{post.post_id}",
            decision_source="two_stage_fixture_provider",
            provider_metadata={"model": "gpt-5.6-sol"},
        )

    def _runtime_source_identity(self) -> str:
        if self._source_identity is None:
            identity = json.loads(
                (self.workspace / CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON).read_text(
                    encoding="utf-8"
                )
            )
            self._source_identity = str(identity["identity_hash"])
        return self._source_identity


def _draw(source_identity: str, user_id: str, message_id: str) -> float:
    key = hashlib.sha256(
        source_identity.encode("utf-8")
        + b"\0"
        + user_id.encode("utf-8")
        + b"\0"
        + message_id.encode("utf-8")
    ).hexdigest()
    digest = hashlib.sha256(f"20260823\0{key}".encode()).digest()
    return (int.from_bytes(digest[:8], "big") >> 11) / float(1 << 53)


def _source_v4(tmp_path: Path) -> tuple[Path, str, str]:
    request = _request(tmp_path / "upstream")
    result = StrictFullPoolFormalReplay().run(
        request,
        adapter_factory=lambda lane_id: _TwoStageFixtureAdapter(lane_id, request.workspace),
    )
    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None
    manifest = json.loads((result.source_root / "manifest.json").read_text(encoding="utf-8"))
    return result.source_root, result.source_manifest_sha256, str(manifest["source_identity"])


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_two_stage_replay_closes_realized_feedback_source_without_provider_calls(
    tmp_path: Path,
) -> None:
    source_root, source_manifest_sha256, source_identity = _source_v4(tmp_path)
    upstream_hashes_before = {
        path.relative_to(source_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_root.rglob("*")
        if path.is_file()
    }
    output = tmp_path / "two-stage-validation"

    result = FullPoolTwoStageReplay().run_and_close(
        FullPoolTwoStageReplayRequest(
            source_root=source_root,
            source_manifest_sha256=source_manifest_sha256,
            source_identity=source_identity,
            output_dir=output,
        )
    )

    assert result.output_dir == output.resolve()
    assert result.user_count == 8
    assert result.pair_count == 24
    assert result.committed_batch_count == 2
    assert result.realization_provider_calls == 0
    assert result.production_deploy_eligible is False

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    evidence = json.loads((output / "realization-evidence.json").read_text(encoding="utf-8"))
    projection = json.loads((output / "realized-projection.json").read_text(encoding="utf-8"))
    terminals = _jsonl(output / "realized-terminal-rows.jsonl")
    commits = _jsonl(output / "batch-commits.jsonl")
    pairs = _jsonl(output / "pair-rows.jsonl")
    candidates = _jsonl(output / "candidate-rows.jsonl")

    assert manifest["schema_version"] == FULL_POOL_TWO_STAGE_SOURCE_SCHEMA
    assert manifest["classification"] == "nonproduction_two_stage_validation"
    assert manifest["formal_research_evidence"] is False
    assert manifest["production_deploy_eligible"] is False
    assert evidence["schema_version"] == FULL_POOL_TWO_STAGE_EVIDENCE_SCHEMA
    assert projection["schema_version"] == FULL_POOL_TWO_STAGE_PROJECTION_SCHEMA
    assert evidence["accounting"]["upstream"]["logical_judgments"] == 24
    assert evidence["accounting"]["upstream"]["observed_model_counts"] == {"gpt-5.6-sol": 24}
    assert evidence["accounting"]["upstream"]["evidence_profile"] == "validation"
    assert evidence["accounting"]["upstream"]["live_api_triggered"] is False
    assert evidence["accounting"]["upstream"]["formal_research_evidence"] is False
    assert evidence["formal_research_evidence"] is False
    assert evidence["accounting"]["realization"] == {
        "live_api_triggered": False,
        "provider_calls": 0,
    }
    assert evidence["accounting"]["composite_zero_provider_formal"] is False

    assert len(terminals) == len(pairs) == 24
    assert len(candidates) == 36
    assert len(commits) == 2
    assert all(len(row) == 24 for row in terminals)
    assert all("realized_reason" not in row for row in terminals)
    assert all(row["provider_reason"].startswith("provider intent for ") for row in terminals)
    assert all(row["provider_confidence"] == 0.73 for row in terminals)
    assert {row["realization_status"] for row in terminals} == {
        "provider_ignore",
        "draw_pass",
        "draw_fail",
    }
    assert all(
        row["uniform_draw"] is None
        and row["realized_action"] == "ignore"
        and row["realized_engage"] is False
        for row in terminals
        if row["realization_status"] == "provider_ignore"
    )
    assert all(
        row["realized_action"] == row["provider_action"]
        for row in terminals
        if row["realization_status"] == "draw_pass"
    )
    assert all(
        row["realized_action"] == "ignore" and row["realized_engage"] is False
        for row in terminals
        if row["realization_status"] == "draw_fail"
    )
    assert {row["provider_action"] for row in terminals if row["provider_engage"]} == {
        "like",
        "comment",
        "share",
    }
    assert any(row["provider_probability"] == 0.0 for row in terminals)
    assert any(row["provider_probability"] == 1.0 for row in terminals)
    assert any(0.0 < float(row["provider_probability"]) < 1.0 for row in terminals)

    batch_zero_positive = sorted(
        {
            str(row["user_id"])
            for row in terminals
            if row["replay_time_step"] == 0 and row["realized_engage"] is True
        }
    )
    assert commits[0]["frozen_realized_positive_user_ids"] == []
    assert commits[0]["committed_realized_positive_user_ids"] == batch_zero_positive
    assert commits[1]["frozen_realized_positive_user_ids"] == batch_zero_positive
    assert all(
        row["campaign_feedback_committed"]
        == (
            row["realized_engage"] is True
            and row["user_id"] in commits[int(row["replay_time_step"])]["committed_realized_positive_user_ids"]
        )
        for row in pairs
    )
    assert all(float(row["campaign_engaged_neighbor_signal"]) == 0.0 for row in candidates if row["time_step"] == 0)

    projection_rows = list(
        csv.DictReader(io.StringIO((output / "full-pool-realized-projection.csv").read_text(encoding="utf-8")))
    )
    assert len(projection_rows) == 18
    assert sum(int(row["Exposure"]) for row in projection_rows) == 24
    action_counts = Counter(str(row["realized_action"]) for row in terminals)
    assert projection["action_counts"] == {
        action: action_counts[action] for action in ("ignore", "like", "comment", "share")
    }
    assert sum(
        int(row["Total Likes"]) + int(row["Total Comments"]) + int(row["Total Shares"])
        for row in projection_rows
    ) == sum(row["realized_engage"] is True for row in terminals)

    upstream_hashes_after = {
        path.relative_to(source_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_root.rglob("*")
        if path.is_file()
    }
    assert upstream_hashes_after == upstream_hashes_before


def test_replay_fails_closed_on_wrong_source_binding_or_schema(tmp_path: Path) -> None:
    source_root, source_manifest_sha256, source_identity = _source_v4(tmp_path)

    with pytest.raises(ValueError, match="manifest|hash"):
        FullPoolTwoStageReplay().run_and_close(
            FullPoolTwoStageReplayRequest(
                source_root=source_root,
                source_manifest_sha256="0" * 64,
                source_identity=source_identity,
                output_dir=tmp_path / "wrong-hash",
            )
        )
    with pytest.raises(ValueError, match="identity"):
        FullPoolTwoStageReplay().run_and_close(
            FullPoolTwoStageReplayRequest(
                source_root=source_root,
                source_manifest_sha256=source_manifest_sha256,
                source_identity="crossed-source-identity",
                output_dir=tmp_path / "wrong-identity",
            )
        )

    schema_path = source_root / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["terminal_variants"] = ["primary", "shadow"]
    schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path = source_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_ref = next(row for row in manifest["artifacts"] if row["relative_path"] == "schema.json")
    schema_ref["sha256"] = hashlib.sha256(schema_path.read_bytes()).hexdigest()
    schema_ref["bytes"] = schema_path.stat().st_size
    manifest["source_hash"] = hashlib.sha256(
        json.dumps(
            manifest["artifacts"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    crossed_manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="schema"):
        FullPoolTwoStageReplay().run_and_close(
            FullPoolTwoStageReplayRequest(
                source_root=source_root,
                source_manifest_sha256=crossed_manifest_sha256,
                source_identity=source_identity,
                output_dir=tmp_path / "wrong-schema",
            )
        )
    assert not (tmp_path / "wrong-hash").exists()
    assert not (tmp_path / "wrong-identity").exists()
    assert not (tmp_path / "wrong-schema").exists()


class _InventoryFixtureSource:
    def __init__(
        self,
        source: _ClosedStrictFullPoolSource,
        batches: list[dict[str, object]],
    ) -> None:
        self.source_identity = source.source_identity
        self.membership = source.membership
        self.facts = SimpleNamespace(committed_batches=len(batches))
        self._batches = batches

    def read_batch(self, time_step: int) -> dict[str, object]:
        return self._batches[time_step]


def test_judgment_inventory_rejects_missing_duplicate_crossed_and_failed_rows(
    tmp_path: Path,
) -> None:
    source_root, source_manifest_sha256, _ = _source_v4(tmp_path)
    from llm_abm_sim.full_pool_source_v4 import read_closed_strict_full_pool_source

    source = read_closed_strict_full_pool_source(
        source_root,
        manifest_sha256=source_manifest_sha256,
    )
    original = [deepcopy(dict(source.read_batch(step))) for step in range(source.facts.committed_batches)]

    mutations: list[tuple[str, object]] = []

    missing = deepcopy(original)
    missing[0]["rows"]["terminal_rows"].pop()  # type: ignore[index,union-attr]
    mutations.append(("missing", missing))

    duplicate = deepcopy(original)
    duplicate_rows = duplicate[0]["rows"]["terminal_rows"]  # type: ignore[index]
    duplicate_rows[1] = deepcopy(duplicate_rows[0])  # type: ignore[index]
    mutations.append(("duplicate", duplicate))

    failed = deepcopy(original)
    failed[0]["rows"]["terminal_rows"][0]["terminal_status"] = "provider_failed"  # type: ignore[index]
    mutations.append(("failed", failed))

    crossed = deepcopy(original)
    crossed[0]["rows"]["terminal_rows"][0]["user_id"] = "u8"  # type: ignore[index]
    mutations.append(("crossed", crossed))

    prompt_drift = deepcopy(original)
    prompt_drift[0]["rows"]["terminal_rows"][0]["prompt_field_inclusion"] = "{}"  # type: ignore[index]
    mutations.append(("Prompt", prompt_drift))

    for _label, batches in mutations:
        with pytest.raises(ValueError, match="mapping|missing|crossed|Prompt|failed"):
            _provider_judgment_inventory(
                _InventoryFixtureSource(source, batches)  # type: ignore[arg-type]
            )
