"""Run-local offline execution seam. No Provider, file publisher or live fallback."""

from __future__ import annotations

import hashlib
from typing import Any

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_study import RULE
from llm_abm_sim.concurrent_message_experiment import (
    _ConcurrentRuntimeKernel,
    _message_user_fit_components,
    _primary_variant_profile,
)
from llm_abm_sim.decision import DecisionInput, EngageDecision
from llm_abm_sim.schemas import PeerContext, PlatformContext


def anchored_draw(anchor: str, seed: int, user: str, message: str) -> float:
    digest = hashlib.sha256(bank.canonical([RULE, anchor, seed, user, message])).digest()
    return (int.from_bytes(digest[:7], "big") >> 3) / 2**53


def decision_input(config: Any, prepared: Any, condition: dict, user: str, message: str, step: int = 0):
    msg = next(m for m in config.messages if m.message_id == message)
    return DecisionInput(
        post=msg.as_post(),
        profile=_primary_variant_profile(prepared.cohort.users_by_id[user]),
        peer_context=PeerContext(),
        platform_context=PlatformContext(),
        time_step=step,
        prompt_version=condition["prompt_version"],
    )


def checked_entries(config: Any, prepared: Any, condition: dict, records: list[dict]):
    indexed = {}
    for row in records:
        key = row["user_id"], row["message_id"], row["client_condition_sha256"]
        if key in indexed:
            raise ValueError("duplicate exact-input judgment")
        indexed[key] = row
    selected = {}
    for user in prepared.cohort.sample_user_ids:
        for message in config.messages:
            data = decision_input(config, prepared, condition, user, message.message_id)
            messages_hash, condition_hash = bank.client_identity(data, condition)
            row = indexed.get((user, message.message_id, condition_hash))
            if row is None:
                raise ValueError("complete candidate judgment bank required; missing input")
            if row["client_messages_sha256"] != messages_hash:
                raise ValueError("client message hash differs")
            EngageDecision.model_validate(row["decision"])
            selected[user, message.message_id] = row
    return selected


def execute(
    config: Any,
    prepared: Any,
    condition: dict,
    records: list[dict],
    *,
    anchor: str,
    seed: int,
    weights: tuple[float, float, float],
    saturation: float,
):
    """Require every candidate judgment before starting; preserve an explicit historical draw anchor."""
    entries = checked_entries(config, prepared, condition, records)
    fits = {
        m.message_id: {
            u: _message_user_fit_components(m, prepared.cohort.users_by_id[u]) for u in prepared.cohort.sample_user_ids
        }
        for m in config.messages
    }

    def resolve(user, message, step):
        entry = entries[user.user_id, message.message_id]
        data = decision_input(config, prepared, condition, user.user_id, message.message_id, step)
        if bank.client_identity(data, condition) != (entry["client_messages_sha256"], entry["client_condition_sha256"]):
            raise ValueError("model-visible input changed during propagation")
        decision = EngageDecision.model_validate(entry["decision"])
        value = anchored_draw(anchor, seed, user.user_id, message.message_id) if decision.engage else None
        positive = value is not None and value < decision.probability
        return {
            "client_condition_sha256": entry["client_condition_sha256"],
            "bank_source": entry["source"],
            "uniform_draw": value,
            "realized_engage": positive,
            "realized_action": decision.action if positive else "ignore",
        }

    return _ConcurrentRuntimeKernel.fixed_judgment_path(
        config=config,
        prepared=prepared,
        weights=weights,
        neighbor_saturation=saturation,
        message_fits=fits,
        resolve=resolve,
    )


def verify(
    path: dict,
    config: Any,
    prepared: Any,
    condition: dict,
    records: list[dict],
    *,
    anchor: str,
    seed: int,
    weights: tuple[float, float, float],
    saturation: float,
):
    """Independent ranking, seed selection, draw and barrier reconstruction; no kernel helpers."""
    entries = checked_entries(config, prepared, condition, records)
    users = prepared.cohort.sample_user_ids
    seeds = set(prepared.cohort.seed_user_ids)
    exposed = {m.message_id: set() for m in config.messages}
    positive_users = set()
    cursor = 0
    if len(path["barriers"]) != config.horizon:
        raise ValueError("barrier count differs")
    for step in range(config.horizon):
        frozen = set(positive_users)
        committed = set()
        for msg in config.messages:
            ranked = []
            for user in users:
                if user in exposed[msg.message_id]:
                    continue
                n = len(prepared.neighbors_by_user.get(user, set()) & frozen)
                fit = _message_user_fit_components(msg, prepared.cohort.users_by_id[user])[1]
                score = (
                    weights[0] * prepared.base_network_by_user.get(user, 0.0)
                    + weights[1] * min(1.0, n / saturation)
                    + weights[2] * fit
                )
                ranked.append((user, score, n))
            ranked.sort(key=lambda r: (-r[1], r[0]))
            if step == 0:
                selected = [r for r in ranked if r[0] in seeds]
                selected += [r for r in ranked if r[0] not in seeds][: config.delivery_capacity - len(selected)]
            else:
                selected = ranked[: config.delivery_capacity]
            if len(selected) != config.delivery_capacity:
                raise ValueError("exposure capacity incomplete")
            for user, score, n in selected:
                entry = entries[user, msg.message_id]
                decision = EngageDecision.model_validate(entry["decision"])
                # Independent spelling of the existing first53 rule.
                digest = hashlib.sha256(bank.canonical([RULE, anchor, seed, user, msg.message_id])).digest()
                value = (int.from_bytes(digest[:7], "big") >> 3) / 9007199254740992 if decision.engage else None
                positive = value is not None and value < decision.probability
                expected = {
                    "time_step": step,
                    "user_id": user,
                    "message_id": msg.message_id,
                    "uniform_draw": value,
                    "realized_engage": positive,
                    "realized_action": decision.action if positive else "ignore",
                    "ranking_score": score,
                    "engaged_neighbor_count": n,
                    "bank_source": entry["source"],
                    "client_condition_sha256": entry["client_condition_sha256"],
                    "selection_reason": ("seed_union" if user in seeds else "personalized_topup")
                    if step == 0
                    else "personalized_top20",
                }
                if cursor >= len(path["terminals"]) or path["terminals"][cursor] != expected:
                    raise ValueError("ranking, tie, draw, action or source differs")
                cursor += 1
                exposed[msg.message_id].add(user)
                if positive:
                    committed.add(user)
        positive_users.update(committed)
        expected_barrier = {
            "time_step": step,
            "exposure_count": len(config.messages) * config.delivery_capacity,
            "frozen_positive_user_ids": sorted(frozen),
            "committed_positive_user_ids": sorted(committed),
            "campaign_positive_user_count": len(positive_users),
        }
        if path["barriers"][step] != expected_barrier:
            raise ValueError("three-message feedback barrier differs")
    if cursor != len(path["terminals"]) or any(
        len(s) != config.horizon * config.delivery_capacity for s in exposed.values()
    ):
        raise ValueError("unique exposure closure differs")
    return {"exposures": cursor, "barriers": config.horizon, "provider_calls": 0}
