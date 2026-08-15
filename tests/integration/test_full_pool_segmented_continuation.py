from __future__ import annotations

import json
from pathlib import Path

from llm_abm_sim.decision import DecisionInput, EngageDecision, LLMDecisionAdapter
from llm_abm_sim.full_pool_segmented_continuation import (
    FullPoolSegmentedContinuation,
    SegmentedContinuationStatus,
)
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile

PREFIX = Path(__file__).parents[1] / "fixtures" / "full_pool_segmented_v1_prefix"
PROMPT_VERSION = "concurrent-primary-observed-v2"
MODEL = "offline-segmented-fixture-v1"


class _IntegrationLane(LLMDecisionAdapter):
    prompt_version = PROMPT_VERSION
    external_request_invocations = 0
    safe_metadata = {
        "adapter": "offline_segmented_fixture",
        "provider": "deterministic",
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "timeout_seconds": 30.0,
        "max_retries": 2,
    }

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.request_invocations = 0

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        del post, peer_context, platform_context, time_step
        self.request_invocations += 1
        self.calls.append(profile.user_id)
        return EngageDecision(
            engage=False,
            probability=0.1,
            confidence=0.9,
            action="ignore",
            reason="offline integration",
            decision_source="offline_segmented_fixture",
            provider_metadata={"model": MODEL},
        )


def _inputs() -> dict[str, DecisionInput]:
    return {
        f"u{number}:message_1:1": DecisionInput(
            post=PostContent(post_id="message_1", text="unchanged prompt semantics"),
            profile=UserProfile(user_id=f"u{number}"),
            peer_context=PeerContext(),
            platform_context=PlatformContext(),
            time_step=1,
            prompt_version=PROMPT_VERSION,
        )
        for number in range(3, 13)
    }


def test_segmented_workspace_is_offline_replayable_without_recreating_lanes(tmp_path: Path) -> None:
    calls: list[str] = []
    workspace = tmp_path / "segmented-source-v2-seam"
    first = FullPoolSegmentedContinuation().run(
        PREFIX,
        workspace,
        continuation_id="offline-integration-v1",
        _fixture_decision_inputs=_inputs(),
        adapter_factory=lambda _lane_id: _IntegrationLane(calls),
    )

    assert first.status is SegmentedContinuationStatus.COMPLETE
    assert set(calls) == {f"u{number}" for number in range(3, 13)}
    assert first.production_deploy_eligible is False
    rows = [
        json.loads(line)
        for line in (first.terminal_rows_path or Path("missing")).read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 13
    assert len({row["pair_id"] for row in rows}) == 13

    factory_called = False

    def tripwire(_lane_id: int) -> LLMDecisionAdapter:
        nonlocal factory_called
        factory_called = True
        raise AssertionError("closed segmented evidence must not recreate Adapters")

    replay = FullPoolSegmentedContinuation().run(
        PREFIX,
        workspace,
        continuation_id="offline-integration-v1",
        _fixture_decision_inputs=_inputs(),
        adapter_factory=tripwire,
    )
    assert replay == first
    assert factory_called is False
