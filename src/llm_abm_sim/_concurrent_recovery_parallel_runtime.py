"""Study-owned bounded batch execution; workers never own persistence or retry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any

from . import concurrent_robustness_v2 as v2
from ._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError
from ._concurrent_recovery_progress import CampaignProgress
from .concurrent_message_experiment import _PairExecutionPlan, _VariantDecisionContext
from .decision import EngageDecision, LLMDecisionAdapter, ProviderDecisionError


class ParallelAdapterPool(LLMDecisionAdapter):
    """Resource carrier at the existing recovery map Seam, never a serial adapter."""

    def __init__(self, lanes: tuple[LLMDecisionAdapter, ...]) -> None:
        if not 1 <= len(lanes) <= 10 or len({id(lane) for lane in lanes}) != len(lanes):
            raise RecoveryCampaignError("Parallel recovery requires one to ten independent adapters")
        self.lanes = lanes

    def decide(
        self, post: Any, profile: Any, peer_context: Any, platform_context: Any = None, time_step: int = 0
    ) -> EngageDecision:
        raise RecoveryCampaignError("Parallel resources require Study-owned keyed batch dispatch")


def preflight_pools(
    manifest: v2.ConcurrentRobustnessManifestV2,
    cells: tuple[v2._PromptModelCell, ...],
    adapters: Mapping[str, LLMDecisionAdapter],
) -> None:
    if set(adapters) != {cell.cell_id for cell in cells} or not all(
        isinstance(a, ParallelAdapterPool) for a in adapters.values()
    ):
        raise RecoveryCampaignError("Parallel resources differ from the frozen model cells")
    pools = {key: value for key, value in adapters.items() if isinstance(value, ParallelAdapterPool)}
    clients: set[int] = set()
    sizes = {len(pool.lanes) for pool in pools.values()}
    if len(sizes) != 1:
        raise RecoveryCampaignError("Parallel cell resources have different capacities")
    for lane in range(next(iter(sizes))):
        mapping = {key: pool.lanes[lane] for key, pool in pools.items()}
        v2._preflight_cell_adapters(manifest, cells, mapping)
        lane_clients = {id(getattr(adapter, "client", None)) for adapter in mapping.values()}
        if len(lane_clients) != 1 or clients & lane_clients:
            raise RecoveryCampaignError("Parallel lanes must have separate provider clients")
        clients.update(lane_clients)


@dataclass(frozen=True)
class FrozenWork:
    coordinates: dict[str, Any]
    context: _VariantDecisionContext

    @property
    def key(self) -> tuple[int, int]:
        return self.coordinates["cell_index"], self.coordinates["pair_schedule_position"]

    def reservation(self) -> dict[str, Any]:
        return {
            "coordinates": dict(self.coordinates),
            "context_sha256": self.context.decision_input(time_step=self.coordinates["time_step"]).cache_key(),
        }


def freeze_work(index: int, cell: v2._PromptModelCell, plans: tuple[_PairExecutionPlan, ...]) -> tuple[FrozenWork, ...]:
    from ._concurrent_recovery_runtime import _coordinates

    return tuple(
        FrozenWork(_coordinates(index, plan), v2._primary_variant_context(plan, prompt_token=cell.prompt_version))
        for plan in plans
    )


def _physical_request(
    adapter: LLMDecisionAdapter, work: FrozenWork
) -> tuple[EngageDecision | None, ProviderDecisionError | None]:
    # Worker does exactly one call. No journal, budget, retry, sleep or credentials.
    context = work.context
    try:
        return adapter.decide(
            post=context.post,
            profile=context.profile,
            peer_context=context.peer_context,
            platform_context=context.platform_context,
            time_step=work.coordinates["time_step"],
        ), None
    except ProviderDecisionError as error:
        return None, error


def run_frozen_batch(
    *,
    state: CampaignProgress,
    journal: CampaignJournal,
    pool: ParallelAdapterPool,
    work: tuple[FrozenWork, ...],
    check_dispatch_window: Callable[[], None],
    backoff_seconds: float,
) -> None:
    """Reserve one frozen batch; dispatch/drain the admitted single-request workers.

    Only the calling Study thread writes durable records or decides retries.
    Persisted successes are reused. A hard failure/unknown stops admission while
    previously dispatched responses drain; unresolved provenance stays unresolved.
    """
    if state.effective_parallel_approval is None or state.status != "running" or state.has_inflight:
        raise RecoveryCampaignError("Parallel batch lacks a resumable admitted extension")
    capacity = state.effective_parallel_approval["maximum_inflight"]
    if len(pool.lanes) != capacity:
        raise RecoveryCampaignError("Parallel pool differs from admitted capacity")
    if not work:
        raise RecoveryCampaignError("Parallel batch cannot be empty")
    batch_key = work[0].coordinates["cell_index"], work[0].coordinates["time_step"]
    document = {"cell_index": batch_key[0], "time_step": batch_key[1], "pairs": [item.reservation() for item in work]}
    existing = state.parallel_batches.get(batch_key)
    if existing is not None and existing != document:
        raise RecoveryCampaignError("Rebuilt parallel batch differs from its frozen inputs")
    remaining = {
        item.key: item
        for item in work
        if item.key not in state.old_successes and item.key not in state.success_decisions
    }
    if not remaining:
        return
    if existing is None:
        state.append(journal, "parallel_batch_reserved", document)
    elif state.parallel_active_batch != batch_key:
        raise RecoveryCampaignError("Parallel work belongs to a completed earlier batch")
    now = v2._V2_MONOTONIC()
    ready_at = {}
    cooldown_until = now
    for key in remaining:
        prior = state.attempts(key)
        delay = prior[-1].wait_seconds or 0.0 if prior and prior[-1].outcome == "retryable_failure" else 0.0
        ready_at[key] = now + delay
        if prior and prior[-1].lane_cooldown:
            cooldown_until = max(cooldown_until, now + delay)
    pending: dict[Future[Any], tuple[FrozenWork, int, int, Any, int]] = {}
    free = list(range(capacity))
    pause: Exception | None = None
    with ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="recovery-physical") as workers:
        while remaining or pending:
            # Drain every already observed completion before any replacement call.
            done = [future for future in pending if future.done()]
            for future in done:
                item, lane, ordinal, before, external_before = pending.pop(future)
                adapter = pool.lanes[lane]
                try:
                    decision, error = future.result()
                except Exception:
                    state.append(
                        journal,
                        "parallel_dispatch_unknown",
                        {"cell_index": item.key[0], "pair_schedule_position": item.key[1], "attempt_number": ordinal},
                    )
                    free.append(lane)
                    continue
                retry = error is not None and error.retryable and ordinal < 3
                delay = None
                source = None
                if retry and error is not None:
                    delay = (
                        error.wait_seconds
                        if error.wait_seconds is not None
                        else min(backoff_seconds * 2 ** (ordinal - 1), v2._V2_BACKOFF_CEILING_SECONDS)
                    )
                    source = (
                        error.wait_source or "provider_wait"
                        if error.wait_seconds is not None
                        else "exponential_backoff"
                    )
                outcome = (
                    "succeeded"
                    if error is None
                    else "retryable_failure"
                    if retry
                    else "attempts_exhausted"
                    if error.retryable
                    else "nonretryable_failure"
                )
                attempt = v2._v2_attempt_evidence(
                    adapter=adapter,
                    before=before,
                    attempt_number=ordinal,
                    outcome=outcome,
                    error=error,
                    wait_seconds=delay,
                    wait_source=source,
                )
                if v2._adapter_external_request_invocations(adapter) - external_before != 1:
                    raise RecoveryCampaignError("Parallel worker transport count differs from one physical intent")
                state.append(
                    journal,
                    "parallel_attempt_settled",
                    {
                        "cell_index": item.key[0],
                        "pair_schedule_position": item.key[1],
                        "attempt": attempt.model_dump(mode="json"),
                        "decision": None
                        if decision is None
                        else decision.model_dump(mode="json", exclude={"provider_metadata"}),
                    },
                )
                if retry and error is not None:
                    remaining[item.key] = item
                    ready_at[item.key] = v2._V2_MONOTONIC() + (delay or 0.0)
                    if error.lane_cooldown:
                        cooldown_until = max(cooldown_until, ready_at[item.key])
                free.append(lane)
            if state.status != "running" or pause is not None:
                remaining.clear()
            while remaining and free and state.status == "running" and pause is None:
                if any(future.done() for future in pending):
                    break
                now = v2._V2_MONOTONIC()
                key = next((key for key in remaining
                            if (state.quota_retry_pending is None or key == state.quota_retry_pending)
                            and max(ready_at[key], cooldown_until) <= now), None)
                if key is None:
                    break
                try:
                    check_dispatch_window()
                except Exception as error:
                    pause = error
                    remaining.clear()
                    break
                item = remaining.pop(key)
                ordinal = len(state.attempts(key)) + 1
                lane = free.pop(0)
                adapter = pool.lanes[lane]
                before = v2._v2_adapter_snapshot(adapter)
                external_before = v2._adapter_external_request_invocations(adapter)
                state.append(
                    journal,
                    "parallel_attempt_intent",
                    {"cell_index": key[0], "pair_schedule_position": key[1], "attempt_number": ordinal},
                )
                future = workers.submit(_physical_request, adapter, item)
                pending[future] = item, lane, ordinal, before, external_before
            if pending:
                timeout = None
                if remaining and free and state.quota_retry_pending is None:
                    timeout = max(
                        0.0, min(max(ready_at[key], cooldown_until) for key in remaining) - v2._V2_MONOTONIC()
                    )
                wait(tuple(pending), timeout=timeout, return_when=FIRST_COMPLETED)
            elif remaining:
                delay = max(0.0, min(max(ready_at[key], cooldown_until) for key in remaining) - v2._V2_MONOTONIC())
                v2._V2_SLEEP(delay)
    if pause is not None:
        raise pause
    if state.status == "stopped":
        raise v2._V2CellStopped("Parallel recovery stopped on a new hard Provider failure")
    if state.status != "running" or state.has_inflight:
        raise RecoveryCampaignError("Parallel recovery requires reconciliation before further dispatch")
